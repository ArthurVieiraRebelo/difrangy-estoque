"""
banco.py
--------
Conexão com o banco de dados (SQLite) e as regras do ESTOQUE.
O app.py (as rotas do site) só chama as funções daqui e nunca escreve SQL.

Regra mais importante do sistema:
    O saldo (quantidade de pijamas / metragem do rolo) NUNCA muda sem que uma
    linha seja gravada na tabela "movimentacoes". As duas coisas acontecem na
    MESMA transação: ou as duas são salvas, ou nenhuma é.

Nas funções que gravam, o parâmetro "usuario" é o funcionário logado
(um dicionário com pelo menos "login" e "perfil"). O login dele fica
gravado em cada movimentação, para saber quem fez o quê.
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

# "Estoque baixo" = saldo menor ou igual ao limite.
# Cada pijama e cada rolo tem o SEU limite (coluna limite_baixo), porque uns
# saem mais que outros. Estes valores são só o que vem preenchido num item novo.
LIMITE_PIJAMAS_BAIXO = 5      # unidades
LIMITE_METROS_BAIXO = 3.0     # metros

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

# Motivos que só o administrador pode usar. O ajuste de inventário corrige o
# saldo "na mão", então fica restrito a quem responde pelo estoque.
MOTIVOS_SO_ADMIN = {"ajuste"}


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


def executar(sql, parametros=()):
    """Roda UM comando que altera o banco (INSERT/UPDATE) e salva.
    Devolve quantas linhas foram alteradas."""
    conexao = conectar()
    try:
        cursor = conexao.execute(sql, parametros)
        conexao.commit()
        return cursor.rowcount
    finally:
        conexao.close()


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
                quantidade  INTEGER NOT NULL DEFAULT 0 CHECK (quantidade >= 0),
                ativo       INTEGER NOT NULL DEFAULT 1,  -- 1 = ativo, 0 = desativado
                -- estoque baixo quando quantidade <= limite_baixo (cada pijama tem o seu)
                limite_baixo INTEGER NOT NULL CHECK (limite_baixo >= 0)
            );

            CREATE TABLE IF NOT EXISTS rolos_tecido (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                codigo          TEXT    UNIQUE,  -- preenchido logo após o INSERT (RL-000001)
                tipo_tecido     TEXT    NOT NULL,
                cor             TEXT    NOT NULL,
                metragem_atual  REAL    NOT NULL DEFAULT 0 CHECK (metragem_atual >= 0),
                ativo           INTEGER NOT NULL DEFAULT 1,
                -- "quase acabando" quando metragem_atual <= limite_baixo (cada rolo tem o seu)
                limite_baixo    REAL    NOT NULL CHECK (limite_baixo >= 0)
            );

            CREATE TABLE IF NOT EXISTS movimentacoes (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                tipo_item    TEXT NOT NULL CHECK (tipo_item IN ('produto', 'rolo')),
                codigo_item  TEXT NOT NULL,
                tipo         TEXT NOT NULL CHECK (tipo IN ('entrada', 'saida')),
                quantidade   REAL NOT NULL CHECK (quantidade > 0),
                data         TEXT NOT NULL,  -- formato 'AAAA-MM-DD HH:MM:SS'
                motivo       TEXT NOT NULL,
                usuario      TEXT            -- login de quem fez a movimentação
            );

            CREATE TABLE IF NOT EXISTS usuarios (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                nome        TEXT    NOT NULL,
                login       TEXT    NOT NULL UNIQUE,
                senha_hash  TEXT    NOT NULL,   -- nunca a senha em si (ver usuarios.py)
                perfil      TEXT    NOT NULL CHECK (perfil IN ('admin', 'operador')),
                ativo       INTEGER NOT NULL DEFAULT 1,
                master      INTEGER NOT NULL DEFAULT 0  -- 1 = dono do sistema (ver usuarios.py)
            );

            -- Configurações do sistema (ex: quais tipos de etiqueta estão liberados).
            -- Cada linha é um par chave/valor, ex: ('etiqueta_qr', '1').
            CREATE TABLE IF NOT EXISTS configuracoes (
                chave  TEXT PRIMARY KEY,
                valor  TEXT NOT NULL
            );

            -- Índices deixam as buscas por código e por data mais rápidas
            CREATE INDEX IF NOT EXISTS idx_mov_codigo ON movimentacoes (codigo_item);
            CREATE INDEX IF NOT EXISTS idx_mov_data   ON movimentacoes (data);
        """)

        # Bancos criados por versões antigas do sistema não têm estas colunas.
        # O CREATE TABLE acima não altera tabelas que já existem, então
        # acrescentamos as colunas que faltarem.
        _adicionar_coluna_se_faltar(conexao, "produtos", "ativo", "INTEGER NOT NULL DEFAULT 1")
        _adicionar_coluna_se_faltar(conexao, "rolos_tecido", "ativo", "INTEGER NOT NULL DEFAULT 1")
        _adicionar_coluna_se_faltar(conexao, "movimentacoes", "usuario", "TEXT")
        _adicionar_coluna_se_faltar(conexao, "usuarios", "master", "INTEGER NOT NULL DEFAULT 0")
        # Os pijamas e rolos que já existiam ficam com o limite padrão (5 un. e 3 m),
        # que era o limite único das versões antigas. Nada muda até o admin alterar.
        _adicionar_coluna_se_faltar(
            conexao, "produtos", "limite_baixo",
            f"INTEGER NOT NULL DEFAULT {LIMITE_PIJAMAS_BAIXO} CHECK (limite_baixo >= 0)",
        )
        _adicionar_coluna_se_faltar(
            conexao, "rolos_tecido", "limite_baixo",
            f"REAL NOT NULL DEFAULT {LIMITE_METROS_BAIXO} CHECK (limite_baixo >= 0)",
        )

        # Se ainda não existe master (banco de uma versão antiga), o administrador
        # mais antigo (o do primeiro acesso, menor id) vira o master.
        conexao.execute("""
            UPDATE usuarios SET master = 1
            WHERE id = (SELECT MIN(id) FROM usuarios WHERE perfil = 'admin')
              AND NOT EXISTS (SELECT 1 FROM usuarios WHERE master = 1)
        """)
        conexao.commit()
    finally:
        conexao.close()


def _adicionar_coluna_se_faltar(conexao, tabela, coluna, definicao):
    """Acrescenta uma coluna numa tabela antiga, se ela ainda não existir.

    O SQLite não aceita "?" no lugar de nomes de tabela/coluna, por isso o SQL
    é montado com f-string. Isso só é seguro porque os nomes vêm escritos no
    próprio código (criar_tabelas), NUNCA de algo digitado pelo usuário.
    """
    colunas = [linha["name"] for linha in conexao.execute(f"PRAGMA table_info({tabela})")]
    if coluna not in colunas:
        conexao.execute(f"ALTER TABLE {tabela} ADD COLUMN {coluna} {definicao}")


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


def limpar_texto(valor, nome_do_campo):
    """Tira espaços das pontas e confere se o campo foi preenchido."""
    texto = str(valor or "").strip()
    if not texto:
        raise ErroEstoque(f"Preencha o campo {nome_do_campo}.")
    if len(texto) > 60:
        raise ErroEstoque(f"O campo {nome_do_campo} pode ter no máximo 60 caracteres.")
    return texto


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
        # Arredondar evita "lixo" de casas decimais (ex: 1 - 0.9 - 0.1 = -0.00000000000000003)
        numero = round(numero, 2)

    if numero < 0 or (numero == 0 and not permitir_zero):
        raise ErroEstoque("A quantidade precisa ser maior que zero.")
    if numero > QUANTIDADE_MAXIMA:
        raise ErroEstoque(f"Quantidade muito alta ({valor}). Confira o que foi digitado.")
    return numero


def converter_limite_baixo(valor, tipo_item="produto"):
    """Valida o "estoque baixo com até X" digitado no cadastro/edição.

    - Pijama: unidades inteiras. Vazio -> LIMITE_PIJAMAS_BAIXO.
    - Rolo: metros, até 2 casas, aceita vírgula ("2,5"). Vazio -> LIMITE_METROS_BAIXO.
    Zero vale: avisa só quando acabar.
    """
    texto = str(valor if valor is not None else "").strip()
    if tipo_item == "produto":
        if not texto:
            return LIMITE_PIJAMAS_BAIXO
        try:
            numero = int(texto)  # int("2.5") dá erro: o limite é em unidades inteiras
        except ValueError:
            raise ErroEstoque(f"Estoque baixo inválido: '{valor}'. Use um número inteiro, ex: 5.")
    else:
        if not texto:
            return LIMITE_METROS_BAIXO
        try:
            numero = round(float(texto.replace(",", ".")), 2)
        except ValueError:
            raise ErroEstoque(f"Limite em metros inválido: '{valor}'. Use um número, ex: 2,5.")
        if not math.isfinite(numero):  # bloqueia "inf" e "nan"
            raise ErroEstoque(f"Limite em metros inválido: '{valor}'. Use um número, ex: 2,5.")
    if numero < 0:
        raise ErroEstoque("O estoque baixo não pode ser negativo.")
    if numero > QUANTIDADE_MAXIMA:
        raise ErroEstoque(f"Estoque baixo muito alto ({valor}). Confira o que foi digitado.")
    return numero


def motivos_permitidos_para(perfil):
    """Os motivos que este perfil pode escolher (o operador não vê o "ajuste").

    Devolve um dicionário no mesmo formato de MOTIVOS_PERMITIDOS.
    """
    resultado = {}
    for tipo_item, por_tipo in MOTIVOS_PERMITIDOS.items():
        resultado[tipo_item] = {}
        for tipo, motivos in por_tipo.items():
            resultado[tipo_item][tipo] = [
                motivo for motivo in motivos
                if perfil == "admin" or motivo not in MOTIVOS_SO_ADMIN
            ]
    return resultado


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
        return _completar_produto(produto)

    rolo = buscar_rolo(codigo)
    if rolo:
        return _completar_rolo(rolo)

    return None


def _completar_produto(produto):
    """Acrescenta ao pijama os campos usados nas telas (tipo, descrição, saldo, unidade)."""
    produto["tipo_item"] = "produto"
    produto["descricao"] = f"Pijama {produto['modelo']} · {produto['tamanho']} · {produto['cor']}"
    produto["saldo"] = produto["quantidade"]
    produto["unidade"] = "un."
    return produto


def _completar_rolo(rolo):
    """Acrescenta ao rolo os campos usados nas telas (tipo, descrição, saldo, unidade)."""
    rolo["tipo_item"] = "rolo"
    rolo["descricao"] = f"Rolo {rolo['tipo_tecido']} · {rolo['cor']}"
    rolo["saldo"] = rolo["metragem_atual"]
    rolo["unidade"] = "m"
    return rolo


# ---------------------------------------------------------------------
# Código digitado "do jeito que der" -> código oficial
# ---------------------------------------------------------------------
# Quem digita à mão pode escrever "pjflomaz", "pj flo m az" ou "PJ.FLO.M.AZ".
# A ideia: comparar só as LETRAS e NÚMEROS ("forma compacta"), ignorando
# maiúsculas/minúsculas, acentos, hífens, espaços e pontos.

def normalizar_texto(texto):
    """'Coração azul' -> 'CORACAO AZUL' (maiúsculo e sem acento), para comparar textos."""
    return unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode().upper()


def compactar_codigo(texto):
    """Só letras e números, em maiúsculo: 'pj-flo m.az' -> 'PJFLOMAZ'."""
    return "".join(c for c in normalizar_texto(texto) if c.isalnum())


def resolver_codigo_digitado(texto):
    """Descobre qual código OFICIAL a pessoa quis digitar.

    Tenta, nesta ordem:
    1. o texto exato (como o leitor de código de barras manda): 'PJ-FLO-M-AZ';
    2. rolo só pelo número: 'rl12' ou 'RL 12' -> 'RL-000012';
    3. um código cuja forma compacta seja igual: 'pjflomaz' -> 'PJ-FLO-M-AZ'.

    Devolve o código oficial, ou None se nenhum item combinar.
    """
    exato = str(texto).strip().upper()
    if exato and buscar_item(exato):
        return exato

    compacto = compactar_codigo(texto)
    if not compacto or len(compacto) > TAMANHO_MAXIMO_CODIGO:
        return None

    prefixo_rolo = compactar_codigo(PREFIXO_ROLO)   # "RL"
    numero = compacto[len(prefixo_rolo):]
    if compacto.startswith(prefixo_rolo) and numero.isdigit() and len(numero) <= 6:
        codigo_rolo = f"{PREFIXO_ROLO}{int(numero):06d}"   # 12 -> RL-000012
        if buscar_rolo(codigo_rolo):
            return codigo_rolo

    # REPLACE(codigo, '-', '') tira os hífens do código guardado no banco
    # (os códigos só têm letras, números e hífen — ver limpar_codigo)
    encontrados = consultar(
        """SELECT codigo FROM produtos     WHERE REPLACE(codigo, '-', '') = ?
           UNION
           SELECT codigo FROM rolos_tecido WHERE REPLACE(codigo, '-', '') = ?""",
        (compacto, compacto),
    )
    if len(encontrados) > 1:
        lista = ", ".join(linha["codigo"] for linha in encontrados)
        raise ErroEstoque(f"'{exato}' combina com mais de um código ({lista}). Digite com os hífens.")
    return encontrados[0]["codigo"] if encontrados else None


def buscar_item_digitado(texto):
    """Igual ao buscar_item, mas aceita o código digitado de qualquer jeito."""
    codigo = resolver_codigo_digitado(texto)
    return buscar_item(codigo) if codigo else None


def sugerir_itens(texto, limite=8):
    """Sugestões para o campo de código da tela Bipar, enquanto a pessoa digita.

    Cada palavra digitada precisa aparecer no código OU na descrição do item:
    'flo az' acha PJ-FLO-M-AZ; 'floral azul' também; 'malha' acha os rolos de malha.
    Só itens ativos. Os que combinam pelo código aparecem primeiro.
    """
    palavras = [compactar_codigo(p) for p in normalizar_texto(texto).split()]
    palavras = [p for p in palavras if p]
    if not palavras:
        return []
    digitado_compacto = compactar_codigo(texto)
    codigo_resolvido = None
    try:
        codigo_resolvido = resolver_codigo_digitado(texto)
    except ErroEstoque:
        pass  # ambíguo: as sugestões mostram as opções para a pessoa escolher

    itens = [_completar_produto(p) for p in listar_produtos(somente_ativos=True)]
    itens += [_completar_rolo(r) for r in listar_rolos(somente_ativos=True)]

    resultado = []
    for item in itens:
        codigo_compacto = compactar_codigo(item["codigo"])
        onde_procurar = codigo_compacto + " " + compactar_codigo(item["descricao"])
        if item["codigo"] != codigo_resolvido and not all(p in onde_procurar for p in palavras):
            continue
        # Ordem: código exato > código começa com o digitado > código contém > só descrição
        if item["codigo"] == codigo_resolvido:
            ordem = 0
        elif codigo_compacto.startswith(digitado_compacto):
            ordem = 1
        elif digitado_compacto in codigo_compacto:
            ordem = 2
        else:
            ordem = 3
        resultado.append((ordem, item["codigo"], item))

    resultado.sort(key=lambda trio: (trio[0], trio[1]))
    return [
        {campo: item[campo] for campo in ("codigo", "descricao", "saldo", "unidade", "tipo_item")}
        for _, _, item in resultado[:limite]
    ]


def listar_produtos(somente_ativos=False):
    """Lista os pijamas. Os ativos aparecem primeiro.

    O truque "(? = 0 OR ...)" deixa usar o MESMO SQL nos dois casos:
    se o parâmetro for 0, a condição é sempre verdadeira e nada é filtrado.
    """
    return consultar(
        """SELECT * FROM produtos
           WHERE (? = 0 OR ativo = 1)
           ORDER BY ativo DESC, modelo, tamanho, cor""",
        (1 if somente_ativos else 0,),
    )


def listar_rolos(somente_com_saldo=False, somente_ativos=False):
    """Lista os rolos. Pode esconder os que acabaram e/ou os desativados."""
    return consultar(
        """SELECT * FROM rolos_tecido
           WHERE (? = 0 OR metragem_atual > 0)
             AND (? = 0 OR ativo = 1)
           ORDER BY ativo DESC, tipo_tecido, cor, codigo""",
        (1 if somente_com_saldo else 0, 1 if somente_ativos else 0),
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
    COALESCE pega o primeiro valor que não for vazio: se o item foi excluído,
    os dois JOINs não acham nada e a descrição vira "(item excluído)".
    """
    return consultar(
        """SELECT m.*,
                  COALESCE(
                      'Pijama ' || p.modelo || ' · ' || p.tamanho || ' · ' || p.cor,
                      'Rolo ' || r.tipo_tecido || ' · ' || r.cor,
                      '(item excluído)'
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
    """Números para os cartões do painel (só itens ativos)."""
    pijamas = consultar_um(
        """SELECT COUNT(*) AS skus,
                  COALESCE(SUM(quantidade), 0) AS unidades,
                  COALESCE(SUM(quantidade <= limite_baixo), 0) AS baixos
           FROM produtos
           WHERE ativo = 1"""
    )
    tecido = consultar_um(
        """SELECT COUNT(*) AS rolos,
                  COALESCE(SUM(metragem_atual), 0) AS metros,
                  COALESCE(SUM(metragem_atual <= limite_baixo), 0) AS baixos
           FROM rolos_tecido
           WHERE metragem_atual > 0 AND ativo = 1"""
    )
    # Observação: no SQLite, uma comparação (quantidade <= limite_baixo) vale 1 ou 0,
    # então SUM(comparação) conta quantas linhas atendem à condição.
    return {
        "pijamas_unidades": pijamas["unidades"],
        "pijamas_skus": pijamas["skus"],
        "rolos_quantidade": tecido["rolos"],
        "rolos_metros": round(tecido["metros"], 2),
        "itens_baixos": pijamas["baixos"] + tecido["baixos"],
    }


# =====================================================================
# Gravações (cadastro, edição e movimentação)
# =====================================================================

def _gravar_movimentacao(conexao, tipo_item, codigo, tipo, quantidade, motivo, usuario):
    """Grava uma linha em movimentacoes usando uma conexão JÁ ABERTA.

    O "_" no começo do nome indica que é uma função interna deste arquivo:
    ela não faz commit, porque quem chamou decide quando salvar tudo junto.
    """
    conexao.execute(
        """INSERT INTO movimentacoes
               (tipo_item, codigo_item, tipo, quantidade, data, motivo, usuario)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (tipo_item, codigo, tipo, quantidade, agora(), motivo, usuario["login"]),
    )


def cadastrar_produto(modelo, tamanho, cor, quantidade_inicial, usuario, codigo="", limite_baixo=""):
    """Cadastra um pijama novo (combinação modelo + tamanho + cor).

    Se o código não for digitado, ele é gerado: PJ-<modelo>-<tamanho>-<cor>.
    Se houver quantidade inicial, grava também a movimentação de entrada.
    limite_baixo: com quantas unidades (ou menos) ele aparece como estoque baixo.
    Devolve o código do pijama cadastrado.
    """
    modelo = limpar_texto(modelo, "modelo")
    tamanho = limpar_texto(tamanho, "tamanho").upper()
    cor = limpar_texto(cor, "cor")
    quantidade = converter_quantidade(quantidade_inicial or 0, "produto", permitir_zero=True)
    limite_baixo = converter_limite_baixo(limite_baixo)

    if str(codigo).strip():
        codigo = limpar_codigo(codigo)
    else:
        codigo = gerar_codigo_produto(modelo, tamanho, cor)

    # Se um pijama pudesse usar "RL-...", ele "roubaria" o código de um rolo futuro
    if codigo.startswith(PREFIXO_ROLO):
        raise ErroEstoque(f"Códigos começando com {PREFIXO_ROLO} são reservados para rolos de tecido.")

    # Código de um pijama EXCLUÍDO não pode voltar a ser usado: o histórico
    # antigo dele passaria a aparecer como se fosse do pijama novo.
    if buscar_produto(codigo) is None and _codigo_tem_historico(codigo):
        raise ErroEstoque(f"O código {codigo} já foi usado por um pijama excluído. Use outro código.")

    conexao = conectar()
    try:
        conexao.execute(
            """INSERT INTO produtos (codigo, modelo, tamanho, cor, quantidade, limite_baixo)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (codigo, modelo, tamanho, cor, quantidade, limite_baixo),
        )
        if quantidade > 0:
            _gravar_movimentacao(conexao, "produto", codigo, "entrada", quantidade,
                                 "estoque_inicial", usuario)
        conexao.commit()
    except sqlite3.IntegrityError:
        # IntegrityError aqui = violou o UNIQUE do código (já existe)
        conexao.rollback()
        raise ErroEstoque(f"Já existe um pijama com o código {codigo}. Digite outro código.")
    finally:
        conexao.close()
    return codigo


def cadastrar_rolo(tipo_tecido, cor, metragem, usuario, limite_baixo=""):
    """Cadastra um rolo novo e grava a entrada da metragem.

    O código é gerado a partir do id: id 1 -> 'RL-000001'.
    Como o id só existe depois do INSERT, fazemos INSERT e logo depois UPDATE,
    tudo na mesma transação.
    limite_baixo: com quantos metros (ou menos) ele aparece como "quase acabando".
    Devolve o código do rolo.
    """
    tipo_tecido = limpar_texto(tipo_tecido, "tipo de tecido")
    cor = limpar_texto(cor, "cor")
    metragem = converter_quantidade(metragem, "rolo")
    limite_baixo = converter_limite_baixo(limite_baixo, "rolo")

    conexao = conectar()
    try:
        cursor = conexao.execute(
            """INSERT INTO rolos_tecido (tipo_tecido, cor, metragem_atual, limite_baixo)
               VALUES (?, ?, ?, ?)""",
            (tipo_tecido, cor, metragem, limite_baixo),
        )
        codigo = f"{PREFIXO_ROLO}{cursor.lastrowid:06d}"  # :06d = 6 dígitos, completando com zeros
        conexao.execute("UPDATE rolos_tecido SET codigo = ? WHERE id = ?", (codigo, cursor.lastrowid))
        _gravar_movimentacao(conexao, "rolo", codigo, "entrada", metragem, "rolo_novo", usuario)
        conexao.commit()
    except Exception:
        conexao.rollback()
        raise
    finally:
        conexao.close()
    return codigo


def editar_produto(codigo, modelo, tamanho, cor, limite_baixo=None):
    """Corrige modelo, tamanho, cor e o limite de estoque baixo de um pijama.

    O CÓDIGO não muda: ele já está impresso nas etiquetas coladas nas peças.
    A QUANTIDADE também não: saldo só muda por movimentação.
    limite_baixo=None mantém o limite que já estava.
    """
    novo_limite = None if limite_baixo is None else converter_limite_baixo(limite_baixo)
    # COALESCE(?, limite_baixo): se o novo limite for None (NULL), fica o atual
    alteradas = executar(
        """UPDATE produtos SET modelo = ?, tamanho = ?, cor = ?,
                               limite_baixo = COALESCE(?, limite_baixo)
           WHERE codigo = ?""",
        (limpar_texto(modelo, "modelo"), limpar_texto(tamanho, "tamanho").upper(),
         limpar_texto(cor, "cor"), novo_limite, codigo),
    )
    if alteradas == 0:
        raise ErroEstoque(f"Pijama {codigo} não encontrado.")


def editar_rolo(codigo, tipo_tecido, cor, limite_baixo=None):
    """Corrige o tipo de tecido, a cor e o limite de "quase acabando" de um rolo.
    Código e metragem não mudam. limite_baixo=None mantém o limite que já estava."""
    novo_limite = None if limite_baixo is None else converter_limite_baixo(limite_baixo, "rolo")
    alteradas = executar(
        """UPDATE rolos_tecido SET tipo_tecido = ?, cor = ?,
                                   limite_baixo = COALESCE(?, limite_baixo)
           WHERE codigo = ?""",
        (limpar_texto(tipo_tecido, "tipo de tecido"), limpar_texto(cor, "cor"), novo_limite, codigo),
    )
    if alteradas == 0:
        raise ErroEstoque(f"Rolo {codigo} não encontrado.")


def _codigo_tem_historico(codigo):
    return consultar_um("SELECT 1 FROM movimentacoes WHERE codigo_item = ? LIMIT 1", (codigo,)) is not None


def excluir_item(codigo):
    """Exclui de vez um pijama ou rolo. Só funciona se ele já estiver DESATIVADO
    (assim ninguém exclui um item em uso por engano, com um clique só).

    As movimentações dele NÃO são apagadas: o histórico e os relatórios continuam
    corretos, e o item aparece lá como "(item excluído)".
    """
    item = buscar_item(codigo)
    if item is None:
        raise ErroEstoque(f"Código {codigo} não encontrado.")
    if item["ativo"]:
        raise ErroEstoque(f"Desative {item['codigo']} antes de excluir.")
    if item["tipo_item"] == "produto":
        executar("DELETE FROM produtos WHERE codigo = ? AND ativo = 0", (item["codigo"],))
    else:
        # Rolos não reaproveitam código: o número vem do id, que nunca se repete
        # (AUTOINCREMENT), então não há risco de misturar históricos.
        executar("DELETE FROM rolos_tecido WHERE codigo = ? AND ativo = 0", (item["codigo"],))
    return item


def definir_item_ativo(codigo, ativo):
    """Desativa (ativo=False) ou reativa (ativo=True) um pijama ou rolo.

    Desativado, ele some do painel e não aceita bipe, mas o histórico continua.
    Só um item desativado pode ser excluído (ver excluir_item).
    """
    item = buscar_item(codigo)
    if item is None:
        raise ErroEstoque(f"Código {codigo} não encontrado.")
    valor = 1 if ativo else 0
    if item["tipo_item"] == "produto":
        executar("UPDATE produtos SET ativo = ? WHERE codigo = ?", (valor, item["codigo"]))
    else:
        executar("UPDATE rolos_tecido SET ativo = ? WHERE codigo = ?", (valor, item["codigo"]))
    return item


def registrar_movimentacao(codigo, tipo, quantidade, motivo, usuario):
    """Entrada ou saída de um item pelo código bipado.

    Devolve o item com o saldo já atualizado (para mostrar na tela).
    """
    digitado = str(codigo).strip()
    if not digitado:
        raise ErroEstoque("Informe um código.")
    if tipo not in ("entrada", "saida"):
        raise ErroEstoque("Escolha entrada ou saída.")

    # Aceita o código digitado de qualquer jeito ("pjflomaz") e acha o oficial
    item = buscar_item_digitado(digitado)
    if item is None:
        raise ErroEstoque(f"Código {digitado.upper()} não encontrado.")
    codigo = item["codigo"]  # daqui para baixo, sempre o código oficial (com hífens)
    if not item["ativo"]:
        raise ErroEstoque(f"{item['descricao']} ({codigo}) está desativado.")

    tipo_item = item["tipo_item"]
    if motivo not in MOTIVOS_PERMITIDOS[tipo_item][tipo]:
        raise ErroEstoque("Motivo inválido para este item.")
    if motivo in MOTIVOS_SO_ADMIN and usuario["perfil"] != "admin":
        raise ErroEstoque(f"Só o administrador pode registrar '{MOTIVOS[motivo]}'.")

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

        _gravar_movimentacao(conexao, tipo_item, codigo, tipo, quantidade, motivo, usuario)
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
    """Pijamas ativos com quantidade menor ou igual ao limite de CADA um."""
    return consultar(
        """SELECT * FROM produtos
           WHERE ativo = 1 AND quantidade <= limite_baixo
           ORDER BY quantidade, modelo"""
    )


def relatorio_rolos_acabando():
    """Rolos ativos com metragem menor ou igual ao limite de CADA um.
    Rolo com 0 m já acabou: não entra (ele não está "acabando")."""
    return consultar(
        """SELECT * FROM rolos_tecido
           WHERE ativo = 1 AND metragem_atual > 0 AND metragem_atual <= limite_baixo
           ORDER BY metragem_atual"""
    )


def relatorio_consumo_tecido_por_mes():
    """Metros cortados por mês, por tipo de tecido e cor.

    substr(data, 1, 7) pega só 'AAAA-MM' da data, para agrupar por mês.
    LEFT JOIN (e não JOIN): cortes de rolos que foram EXCLUÍDOS continuam
    somando, agrupados como "(item excluído)" — assim o total de um mês
    passado nunca muda depois que um rolo é excluído.
    """
    return consultar(
        """SELECT substr(m.data, 1, 7) AS mes,
                  COALESCE(r.tipo_tecido, '(item excluído)') AS tipo_tecido,
                  COALESCE(r.cor, '—') AS cor,
                  ROUND(SUM(m.quantidade), 2) AS metros
           FROM movimentacoes m
           LEFT JOIN rolos_tecido r ON r.codigo = m.codigo_item
           WHERE m.tipo_item = 'rolo' AND m.tipo = 'saida' AND m.motivo = 'corte'
           GROUP BY mes, tipo_tecido, cor
           ORDER BY mes DESC, metros DESC"""
    )


def relatorio_pijamas_vendidos_por_mes():
    """Pijamas vendidos por mês, por modelo (LEFT JOIN pelo mesmo motivo do relatório acima)."""
    return consultar(
        """SELECT substr(m.data, 1, 7) AS mes,
                  COALESCE(p.modelo, '(item excluído)') AS modelo,
                  CAST(SUM(m.quantidade) AS INTEGER) AS unidades
           FROM movimentacoes m
           LEFT JOIN produtos p ON p.codigo = m.codigo_item
           WHERE m.tipo_item = 'produto' AND m.tipo = 'saida' AND m.motivo = 'venda'
           GROUP BY mes, modelo
           ORDER BY mes DESC, unidades DESC"""
    )
