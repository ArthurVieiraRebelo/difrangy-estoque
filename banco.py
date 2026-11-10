"""
banco.py
--------
Tudo que conversa com o banco de dados (SQLite) fica neste arquivo.
O app.py (as rotas do site) só chama as funções daqui e nunca escreve SQL.

Regra mais importante do sistema:
    O saldo (quantidade de pijamas / metragem do rolo) NUNCA muda sem que uma
    linha seja gravada na tabela "movimentacoes". As duas coisas acontecem na
    MESMA transação: ou as duas são salvas, ou nenhuma é.
"""

import math
import os
import sqlite3
import unicodedata
from datetime import datetime
from pathlib import Path

# O arquivo do banco fica na mesma pasta deste arquivo .py.
# A variável de ambiente ESTOQUE_DB permite usar outro arquivo — os testes
# usam isso para trabalhar num banco temporário, sem mexer no estoque real.
CAMINHO_BANCO = Path(os.environ.get("ESTOQUE_DB", Path(__file__).parent / "estoque.db"))

# Itens com saldo menor ou igual a estes valores aparecem como "estoque baixo"
LIMITE_PIJAMAS_BAIXO = 5
LIMITE_METROS_BAIXO = 3.0

# Proteções contra erro de digitação (ex: bipar o código no campo de quantidade)
QUANTIDADE_MAXIMA = 100_000      # por movimentação (unidades ou metros)
TAMANHO_MAXIMO_CODIGO = 30       # letras no código de barras

# Códigos que começam assim são reservados para rolos de tecido
PREFIXO_ROLO = "RL-"

# Motivos das movimentações.
# A chave (esquerda) é o que fica gravado no banco; o valor é o texto mostrado na tela.
MOTIVOS = {
    "producao": "Produção",
    "venda": "Venda",
    "perda": "Perda / defeito",
    "ajuste": "Ajuste de inventário",
    "corte": "Corte de tecido",
    "rolo_novo": "Rolo novo (cadastro)",
    "estoque_inicial": "Estoque inicial (cadastro)",
}

# Quais motivos o funcionário pode escolher em cada situação.
# Ex: MOTIVOS_PERMITIDOS["rolo"]["saida"] -> motivos para tirar metros de um rolo.
# ("rolo_novo" e "estoque_inicial" não aparecem aqui porque só o cadastro usa.)
MOTIVOS_PERMITIDOS = {
    "produto": {
        "entrada": ["producao", "ajuste"],
        "saida": ["venda", "perda", "ajuste"],
    },
    "rolo": {
        "entrada": ["ajuste"],
        "saida": ["corte", "perda", "ajuste"],
    },
}


class ErroEstoque(Exception):
    """Erro de regra de negócio (código inexistente, estoque insuficiente...).

    A mensagem deste erro é mostrada para o funcionário na tela.
    """


# =====================================================================
# Conexão e criação das tabelas
# =====================================================================

def conectar():
    """Abre uma conexão com o banco.

    timeout=10: se outro computador estiver gravando no mesmo instante,
                espera até 10 segundos em vez de dar erro na hora.
    row_factory: permite ler cada linha como dicionário: linha["codigo"].
    """
    conexao = sqlite3.connect(CAMINHO_BANCO, timeout=10)
    conexao.row_factory = sqlite3.Row
    return conexao


def consultar(sql, parametros=()):
    """Roda um SELECT e devolve uma lista de dicionários (um por linha)."""
    conexao = conectar()
    try:
        linhas = conexao.execute(sql, parametros).fetchall()
    finally:
        conexao.close()  # "finally" garante que fecha mesmo se der erro
    return [dict(linha) for linha in linhas]


def consultar_um(sql, parametros=()):
    """Igual ao consultar(), mas devolve só a primeira linha (ou None)."""
    linhas = consultar(sql, parametros)
    return linhas[0] if linhas else None


def criar_tabelas():
    """Cria as tabelas se ainda não existirem. É chamada quando o sistema inicia."""
    conexao = conectar()
    try:
        # Modo WAL: permite que os computadores LEIAM o banco enquanto outro
        # está GRAVANDO. Importante porque o painel consulta a cada 3 segundos.
        conexao.execute("PRAGMA journal_mode = WAL")

        # Os CHECK abaixo são uma segunda proteção: mesmo que o código Python
        # tenha algum erro, o próprio banco recusa saldo negativo.
        conexao.executescript("""
            CREATE TABLE IF NOT EXISTS produtos (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                codigo      TEXT    NOT NULL UNIQUE,
                modelo      TEXT    NOT NULL,
                tamanho     TEXT    NOT NULL,
                cor         TEXT    NOT NULL,
                quantidade  INTEGER NOT NULL DEFAULT 0 CHECK (quantidade >= 0)
            );

            CREATE TABLE IF NOT EXISTS rolos_tecido (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                codigo          TEXT    UNIQUE,  -- preenchido logo após o INSERT (RL-000001)
                tipo_tecido     TEXT    NOT NULL,
                cor             TEXT    NOT NULL,
                metragem_atual  REAL    NOT NULL DEFAULT 0 CHECK (metragem_atual >= 0)
            );

            CREATE TABLE IF NOT EXISTS movimentacoes (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                tipo_item    TEXT NOT NULL CHECK (tipo_item IN ('produto', 'rolo')),
                codigo_item  TEXT NOT NULL,
                tipo         TEXT NOT NULL CHECK (tipo IN ('entrada', 'saida')),
                quantidade   REAL NOT NULL CHECK (quantidade > 0),
                data         TEXT NOT NULL,  -- formato 'AAAA-MM-DD HH:MM:SS'
                motivo       TEXT NOT NULL
            );

            -- Índices deixam as buscas por código e por data mais rápidas
            CREATE INDEX IF NOT EXISTS idx_mov_codigo ON movimentacoes (codigo_item);
            CREATE INDEX IF NOT EXISTS idx_mov_data   ON movimentacoes (data);
        """)
        conexao.commit()
    finally:
        conexao.close()


# =====================================================================
# Funções auxiliares (validação e formatação)
# =====================================================================

def agora():
    """Data e hora atual em texto. Esse formato o SQLite consegue ordenar certo."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def sigla(texto, tamanho):
    """Gera uma sigla: sigla('Floral', 3) -> 'FLO'; sigla('Água', 2) -> 'AG'.

    normalize("NFKD") separa a letra do acento (á vira a + ´) e o
    encode("ascii", "ignore") joga fora o que não é letra simples (o acento).
    """
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    so_letras_e_numeros = "".join(c for c in sem_acento if c.isalnum())
    return so_letras_e_numeros.upper()[:tamanho]


def gerar_codigo_produto(modelo, tamanho, cor):
    """Monta o código do pijama: Floral, M, Azul -> 'PJ-FLO-M-AZ'."""
    return f"PJ-{sigla(modelo, 3)}-{sigla(tamanho, 3)}-{sigla(cor, 2)}"


def limpar_codigo(codigo):
    """Padroniza o código (sem espaços, maiúsculo) e confere se só tem
    letras, números e hífen. Devolve o código limpo."""
    codigo = str(codigo).strip().upper()
    if not codigo:
        raise ErroEstoque("Informe um código.")
    if len(codigo) > TAMANHO_MAXIMO_CODIGO:
        raise ErroEstoque(f"Código muito longo (máximo {TAMANHO_MAXIMO_CODIGO} caracteres).")
    if not all(c.isascii() and (c.isalnum() or c == "-") for c in codigo):
        raise ErroEstoque(f"Código inválido: {codigo}. Use só letras, números e hífen.")
    return codigo


def converter_quantidade(valor, tipo_item, permitir_zero=False):
    """Converte o que foi digitado em número e valida.

    - Pijama: número inteiro (unidades).
    - Rolo: decimal com até 2 casas. Aceita vírgula ("12,5") ou ponto ("12.5").
    """
    texto = str(valor).strip().replace(",", ".")
    try:
        numero = float(texto)
    except ValueError:
        raise ErroEstoque(f"Quantidade inválida: '{valor}'.")

    if not math.isfinite(numero):  # bloqueia "inf" e "nan", que o float() aceita
        raise ErroEstoque(f"Quantidade inválida: '{valor}'.")

    if tipo_item == "produto":
        if not numero.is_integer():
            raise ErroEstoque("Pijama é contado em unidades inteiras.")
        numero = int(numero)
    else:
        # Arredondar evita "lixo" de casas decimais (ex: 10 - 3.3 - 6.7 = 0.0000000000000018)
        numero = round(numero, 2)

    if numero < 0 or (numero == 0 and not permitir_zero):
        raise ErroEstoque("A quantidade precisa ser maior que zero.")
    if numero > QUANTIDADE_MAXIMA:
        raise ErroEstoque(f"Quantidade muito alta ({valor}). Confira o que foi digitado.")
    return numero


# =====================================================================
# Consultas (leitura)
# =====================================================================

def buscar_produto(codigo):
    return consultar_um("SELECT * FROM produtos WHERE codigo = ?", (codigo,))


def buscar_rolo(codigo):
    return consultar_um("SELECT * FROM rolos_tecido WHERE codigo = ?", (codigo,))


def buscar_item(codigo):
    """Descobre se o código bipado é de um pijama ou de um rolo.

    Devolve um dicionário com os dados do item e mais alguns campos que
    facilitam mostrar na tela: tipo_item, descricao, saldo e unidade.
    Devolve None se o código não existir.
    """
    codigo = str(codigo).strip().upper()

    produto = buscar_produto(codigo)
    if produto:
        produto["tipo_item"] = "produto"
        produto["descricao"] = f"Pijama {produto['modelo']} · {produto['tamanho']} · {produto['cor']}"
        produto["saldo"] = produto["quantidade"]
        produto["unidade"] = "un."
        return produto

    rolo = buscar_rolo(codigo)
    if rolo:
        rolo["tipo_item"] = "rolo"
        rolo["descricao"] = f"Rolo {rolo['tipo_tecido']} · {rolo['cor']}"
        rolo["saldo"] = rolo["metragem_atual"]
        rolo["unidade"] = "m"
        return rolo

    return None


def listar_produtos():
    return consultar("SELECT * FROM produtos ORDER BY modelo, tamanho, cor")


def listar_rolos(somente_com_saldo=False):
    """Lista os rolos. Com somente_com_saldo=True, esconde os rolos que já acabaram.

    O truque "(? = 0 OR ...)" deixa usar o MESMO SQL nos dois casos:
    se o parâmetro for 0, a condição é sempre verdadeira e nada é filtrado.
    """
    return consultar(
        """SELECT * FROM rolos_tecido
           WHERE (? = 0 OR metragem_atual > 0)
           ORDER BY tipo_tecido, cor, codigo""",
        (1 if somente_com_saldo else 0,),
    )


def listar_valores_distintos(campo):
    """Lista os valores já usados (ex: todos os modelos), para sugerir no formulário.

    "campo" é um nome FIXO escolhido no próprio código (nunca algo digitado
    pelo usuário). Cada campo tem sua consulta pronta no dicionário abaixo,
    assim nenhum SQL é montado juntando textos.
    """
    consultas = {
        "modelo": "SELECT DISTINCT modelo AS valor FROM produtos ORDER BY modelo",
        "cor_produto": "SELECT DISTINCT cor AS valor FROM produtos ORDER BY cor",
        "tipo_tecido": "SELECT DISTINCT tipo_tecido AS valor FROM rolos_tecido ORDER BY tipo_tecido",
        "cor_rolo": "SELECT DISTINCT cor AS valor FROM rolos_tecido ORDER BY cor",
    }
    return [linha["valor"] for linha in consultar(consultas[campo])]


def listar_movimentacoes(limite=50, codigo=""):
    """Últimas movimentações (as mais novas primeiro).

    Se "codigo" for informado, mostra só as daquele item.
    O LEFT JOIN busca a descrição do item na tabela certa (produtos ou rolos).
    """
    return consultar(
        """SELECT m.*,
                  COALESCE(
                      'Pijama ' || p.modelo || ' · ' || p.tamanho || ' · ' || p.cor,
                      'Rolo ' || r.tipo_tecido || ' · ' || r.cor
                  ) AS descricao
           FROM movimentacoes m
           LEFT JOIN produtos p
                  ON m.tipo_item = 'produto' AND p.codigo = m.codigo_item
           LEFT JOIN rolos_tecido r
                  ON m.tipo_item = 'rolo' AND r.codigo = m.codigo_item
           WHERE (? = '' OR m.codigo_item = ?)
           ORDER BY m.id DESC
           LIMIT ?""",
        (codigo, codigo, limite),
    )


def resumo():
    """Números para os cartões do painel."""
    pijamas = consultar_um(
        """SELECT COUNT(*) AS skus,
                  COALESCE(SUM(quantidade), 0) AS unidades,
                  COALESCE(SUM(quantidade <= ?), 0) AS baixos
           FROM produtos""",
        (LIMITE_PIJAMAS_BAIXO,),
    )
    tecido = consultar_um(
        """SELECT COUNT(*) AS rolos,
                  COALESCE(SUM(metragem_atual), 0) AS metros,
                  COALESCE(SUM(metragem_atual <= ?), 0) AS baixos
           FROM rolos_tecido
           WHERE metragem_atual > 0""",
        (LIMITE_METROS_BAIXO,),
    )
    # Observação: no SQLite, uma comparação (quantidade <= 5) vale 1 ou 0,
    # então SUM(comparação) conta quantas linhas atendem à condição.
    return {
        "pijamas_unidades": pijamas["unidades"],
        "pijamas_skus": pijamas["skus"],
        "rolos_quantidade": tecido["rolos"],
        "rolos_metros": round(tecido["metros"], 2),
        "itens_baixos": pijamas["baixos"] + tecido["baixos"],
    }


# =====================================================================
# Gravações (cadastro e movimentação)
# =====================================================================

def _gravar_movimentacao(conexao, tipo_item, codigo, tipo, quantidade, motivo):
    """Grava uma linha em movimentacoes usando uma conexão JÁ ABERTA.

    O "_" no começo do nome indica que é uma função interna deste arquivo:
    ela não faz commit, porque quem chamou decide quando salvar tudo junto.
    """
    conexao.execute(
        """INSERT INTO movimentacoes (tipo_item, codigo_item, tipo, quantidade, data, motivo)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (tipo_item, codigo, tipo, quantidade, agora(), motivo),
    )


def cadastrar_produto(modelo, tamanho, cor, quantidade_inicial, codigo=""):
    """Cadastra um pijama novo (combinação modelo + tamanho + cor).

    Se o código não for digitado, ele é gerado: PJ-<modelo>-<tamanho>-<cor>.
    Se houver quantidade inicial, grava também a movimentação de entrada.
    Devolve o código do pijama cadastrado.
    """
    modelo, tamanho, cor = modelo.strip(), tamanho.strip().upper(), cor.strip()
    if not modelo or not tamanho or not cor:
        raise ErroEstoque("Preencha modelo, tamanho e cor.")

    quantidade = converter_quantidade(quantidade_inicial or 0, "produto", permitir_zero=True)

    if codigo.strip():
        codigo = limpar_codigo(codigo)
    else:
        codigo = gerar_codigo_produto(modelo, tamanho, cor)

    # Se um pijama pudesse usar "RL-...", ele "roubaria" o código de um rolo futuro
    if codigo.startswith(PREFIXO_ROLO):
        raise ErroEstoque(f"Códigos começando com {PREFIXO_ROLO} são reservados para rolos de tecido.")

    conexao = conectar()
    try:
        conexao.execute(
            """INSERT INTO produtos (codigo, modelo, tamanho, cor, quantidade)
               VALUES (?, ?, ?, ?, ?)""",
            (codigo, modelo, tamanho, cor, quantidade),
        )
        if quantidade > 0:
            _gravar_movimentacao(conexao, "produto", codigo, "entrada", quantidade, "estoque_inicial")
        conexao.commit()
    except sqlite3.IntegrityError:
        # IntegrityError aqui = violou o UNIQUE do código (já existe)
        conexao.rollback()
        raise ErroEstoque(f"Já existe um pijama com o código {codigo}. Digite outro código.")
    finally:
        conexao.close()
    return codigo


def cadastrar_rolo(tipo_tecido, cor, metragem):
    """Cadastra um rolo novo e grava a entrada da metragem.

    O código é gerado a partir do id: id 1 -> 'RL-000001'.
    Como o id só existe depois do INSERT, fazemos INSERT e logo depois UPDATE,
    tudo na mesma transação. Devolve o código do rolo.
    """
    tipo_tecido, cor = tipo_tecido.strip(), cor.strip()
    if not tipo_tecido or not cor:
        raise ErroEstoque("Preencha o tipo de tecido e a cor.")
    metragem = converter_quantidade(metragem, "rolo")

    conexao = conectar()
    try:
        cursor = conexao.execute(
            "INSERT INTO rolos_tecido (tipo_tecido, cor, metragem_atual) VALUES (?, ?, ?)",
            (tipo_tecido, cor, metragem),
        )
        codigo = f"{PREFIXO_ROLO}{cursor.lastrowid:06d}"  # :06d = 6 dígitos, completando com zeros
        conexao.execute("UPDATE rolos_tecido SET codigo = ? WHERE id = ?", (codigo, cursor.lastrowid))
        _gravar_movimentacao(conexao, "rolo", codigo, "entrada", metragem, "rolo_novo")
        conexao.commit()
    except Exception:
        conexao.rollback()
        raise
    finally:
        conexao.close()
    return codigo


def registrar_movimentacao(codigo, tipo, quantidade, motivo):
    """Entrada ou saída de um item pelo código bipado.

    Devolve o item com o saldo já atualizado (para mostrar na tela).
    """
    codigo = limpar_codigo(codigo)
    if tipo not in ("entrada", "saida"):
        raise ErroEstoque("Escolha entrada ou saída.")

    item = buscar_item(codigo)
    if item is None:
        raise ErroEstoque(f"Código {codigo} não encontrado.")

    tipo_item = item["tipo_item"]
    if motivo not in MOTIVOS_PERMITIDOS[tipo_item][tipo]:
        raise ErroEstoque("Motivo inválido para este item.")

    quantidade = converter_quantidade(quantidade, tipo_item)
    # Na saída a variação é negativa: tira do estoque.
    variacao = quantidade if tipo == "entrada" else -quantidade

    conexao = conectar()
    try:
        # O UPDATE só acontece se o saldo NÃO ficar negativo (condição no WHERE).
        # Fazer a conferência e a alteração num comando só evita o problema de
        # dois computadores tirarem a última unidade ao mesmo tempo.
        if tipo_item == "produto":
            cursor = conexao.execute(
                """UPDATE produtos SET quantidade = quantidade + ?
                   WHERE codigo = ? AND quantidade + ? >= 0""",
                (variacao, codigo, variacao),
            )
        else:
            cursor = conexao.execute(
                """UPDATE rolos_tecido SET metragem_atual = ROUND(metragem_atual + ?, 2)
                   WHERE codigo = ? AND ROUND(metragem_atual + ?, 2) >= 0""",
                (variacao, codigo, variacao),
            )

        # rowcount = quantas linhas o UPDATE alterou. 0 = a condição falhou.
        if cursor.rowcount == 0:
            raise ErroEstoque(
                f"Estoque insuficiente — saldo atual de {codigo}: {item['saldo']} {item['unidade']}"
            )

        _gravar_movimentacao(conexao, tipo_item, codigo, tipo, quantidade, motivo)
        conexao.commit()
    except Exception:
        conexao.rollback()  # desfaz o UPDATE se qualquer coisa deu errado
        raise
    finally:
        conexao.close()

    return buscar_item(codigo)


# =====================================================================
# Relatórios
# =====================================================================

def relatorio_pijamas_baixos():
    return consultar(
        "SELECT * FROM produtos WHERE quantidade <= ? ORDER BY quantidade, modelo",
        (LIMITE_PIJAMAS_BAIXO,),
    )


def relatorio_rolos_acabando():
    return consultar(
        """SELECT * FROM rolos_tecido
           WHERE metragem_atual > 0 AND metragem_atual <= ?
           ORDER BY metragem_atual""",
        (LIMITE_METROS_BAIXO,),
    )


def relatorio_consumo_tecido_por_mes():
    """Metros cortados por mês, por tipo de tecido e cor.

    substr(data, 1, 7) pega só 'AAAA-MM' da data, para agrupar por mês.
    """
    return consultar(
        """SELECT substr(m.data, 1, 7) AS mes,
                  r.tipo_tecido, r.cor,
                  ROUND(SUM(m.quantidade), 2) AS metros
           FROM movimentacoes m
           JOIN rolos_tecido r ON r.codigo = m.codigo_item
           WHERE m.tipo_item = 'rolo' AND m.tipo = 'saida' AND m.motivo = 'corte'
           GROUP BY mes, r.tipo_tecido, r.cor
           ORDER BY mes DESC, metros DESC"""
    )


def relatorio_pijamas_vendidos_por_mes():
    """Pijamas vendidos por mês, por modelo."""
    return consultar(
        """SELECT substr(m.data, 1, 7) AS mes,
                  p.modelo,
                  CAST(SUM(m.quantidade) AS INTEGER) AS unidades
           FROM movimentacoes m
           JOIN produtos p ON p.codigo = m.codigo_item
           WHERE m.tipo_item = 'produto' AND m.tipo = 'saida' AND m.motivo = 'venda'
           GROUP BY mes, p.modelo
           ORDER BY mes DESC, unidades DESC"""
    )
