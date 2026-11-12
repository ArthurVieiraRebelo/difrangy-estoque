"""
migracoes.py
------------
Cria o banco novo ou atualiza um banco antigo até a versão atual.

Por que existe:
    O SQLite não deixa acrescentar uma regra (UNIQUE, CHECK, chave estrangeira)
    numa tabela que já existe. Para mudar a estrutura, é preciso criar a tabela
    nova, copiar os dados e trocar uma pela outra. Fazer isso "de qualquer jeito"
    é o jeito mais fácil de perder dados depois de anos de uso.

Como funciona:
    - O banco guarda o número da sua versão em PRAGMA user_version (começa em 0).
    - Cada mudança de estrutura é uma função _migracao_N, registrada em MIGRACOES.
    - Ao iniciar, o sistema roda, em ordem, só as migrações que faltam.
    - Cada migração roda numa transação: ou ela inteira é salva, ou nada muda.
    - Antes de atualizar um banco que já tem dados, é feito um backup.

Regra para o futuro: NUNCA altere uma migração que já foi usada. Para mudar a
estrutura de novo, escreva uma _migracao_3 e acrescente em MIGRACOES. Por isso
os números (30 letras no código, motivos...) estão escritos aqui dentro, e não
lidos das constantes do banco.py: a migração 2 tem que fazer sempre a mesma
coisa, mesmo que as constantes mudem um dia.
"""

import sqlite3

import banco


class ErroMigracao(Exception):
    """O banco não pôde ser atualizado. Nada foi alterado (a transação foi desfeita)."""


# =====================================================================
# Migração 1 — a estrutura das primeiras versões do sistema
# =====================================================================
# Bancos criados antes do controle de versão têm user_version = 0 e podem
# estar em qualquer ponto da evolução (sem a coluna "ativo", sem "master"...).
# Esta migração leva qualquer um deles ao mesmo ponto: a estrutura da versão
# anterior ao controle de versão. Num banco novo, ela só cria as tabelas.

def _migracao_1(conexao):
    comandos = [
        """CREATE TABLE IF NOT EXISTS produtos (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               codigo TEXT NOT NULL UNIQUE, modelo TEXT NOT NULL,
               tamanho TEXT NOT NULL, cor TEXT NOT NULL,
               quantidade INTEGER NOT NULL DEFAULT 0 CHECK (quantidade >= 0))""",
        """CREATE TABLE IF NOT EXISTS rolos_tecido (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               codigo TEXT UNIQUE, tipo_tecido TEXT NOT NULL, cor TEXT NOT NULL,
               metragem_atual REAL NOT NULL DEFAULT 0 CHECK (metragem_atual >= 0))""",
        """CREATE TABLE IF NOT EXISTS movimentacoes (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               tipo_item TEXT NOT NULL CHECK (tipo_item IN ('produto', 'rolo')),
               codigo_item TEXT NOT NULL,
               tipo TEXT NOT NULL CHECK (tipo IN ('entrada', 'saida')),
               quantidade REAL NOT NULL CHECK (quantidade > 0),
               data TEXT NOT NULL, motivo TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS usuarios (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               nome TEXT NOT NULL, login TEXT NOT NULL UNIQUE, senha_hash TEXT NOT NULL,
               perfil TEXT NOT NULL CHECK (perfil IN ('admin', 'operador')))""",
        """CREATE TABLE IF NOT EXISTS configuracoes (
               chave TEXT PRIMARY KEY, valor TEXT NOT NULL)""",
    ]
    for sql in comandos:
        conexao.execute(sql)

    # Colunas que foram surgindo nas versões antigas
    _adicionar_coluna_se_faltar(conexao, "produtos", "ativo", "INTEGER NOT NULL DEFAULT 1")
    _adicionar_coluna_se_faltar(conexao, "produtos", "limite_baixo", "INTEGER NOT NULL DEFAULT 5")
    _adicionar_coluna_se_faltar(conexao, "rolos_tecido", "ativo", "INTEGER NOT NULL DEFAULT 1")
    _adicionar_coluna_se_faltar(conexao, "rolos_tecido", "limite_baixo", "REAL NOT NULL DEFAULT 3.0")
    _adicionar_coluna_se_faltar(conexao, "movimentacoes", "usuario", "TEXT")
    _adicionar_coluna_se_faltar(conexao, "usuarios", "ativo", "INTEGER NOT NULL DEFAULT 1")
    _adicionar_coluna_se_faltar(conexao, "usuarios", "master", "INTEGER NOT NULL DEFAULT 0")

    # Banco sem master (de antes de ele existir): o administrador mais antigo vira o master
    conexao.execute("""
        UPDATE usuarios SET master = 1
        WHERE id = (SELECT MIN(id) FROM usuarios WHERE perfil = 'admin')
          AND NOT EXISTS (SELECT 1 FROM usuarios WHERE master = 1)
    """)


def _adicionar_coluna_se_faltar(conexao, tabela, coluna, definicao):
    """Acrescenta uma coluna numa tabela antiga, se ela ainda não existir.

    O SQLite não aceita "?" no lugar de nomes de tabela/coluna, por isso o SQL
    é montado com f-string. Isso só é seguro porque os nomes vêm escritos neste
    arquivo, NUNCA de algo digitado pelo usuário.
    """
    colunas = [linha["name"] for linha in conexao.execute(f"PRAGMA table_info({tabela})")]
    if coluna not in colunas:
        conexao.execute(f"ALTER TABLE {tabela} ADD COLUMN {coluna} {definicao}")


# =====================================================================
# Migração 2 — as regras passam a ser garantidas pelo próprio banco
# =====================================================================
# Antes, várias regras eram conferidas só pelo Python. Se um dia o código
# tivesse um erro (ou alguém mexesse no banco por fora), o banco aceitaria
# dados errados em silêncio. Agora o próprio banco recusa:
#   - o mesmo pijama (modelo + tamanho + cor) cadastrado duas vezes;
#   - movimentação de um item que não existe ou está desativado;
#   - movimentação feita por um usuário que não existe (chave estrangeira);
#   - alterar ou apagar uma linha do histórico;
#   - mudar o código de um item (ele está impresso nas etiquetas);
#   - apagar de verdade um item ou usuário (o histórico apontaria para o nada);
#   - valores fora do permitido (ativo = 7, motivo inventado, data torta...).
#
# Itens "excluídos" passam a ficar no banco com excluido = 1 (exclusão lógica):
# somem de todas as telas, mas o histórico continua ligado a eles.

# Motivos que existiam quando esta migração foi escrita (ver banco.MOTIVOS).
_MOTIVOS_V2 = "('producao', 'venda', 'perda', 'ajuste', 'corte', 'rolo_novo', 'estoque_inicial')"

_TABELAS_V2 = [
    """CREATE TABLE produtos (
           id            INTEGER PRIMARY KEY AUTOINCREMENT,
           -- Código da etiqueta: só A-Z, 0-9 e hífen, até 30 letras, nunca começa com RL-
           codigo        TEXT    NOT NULL UNIQUE
                                 CHECK (length(codigo) BETWEEN 1 AND 30
                                        AND codigo NOT GLOB '*[^A-Z0-9-]*'
                                        AND codigo NOT LIKE 'RL-%'),
           modelo        TEXT    NOT NULL CHECK (trim(modelo) <> ''),
           tamanho       TEXT    NOT NULL CHECK (trim(tamanho) <> ''),
           cor           TEXT    NOT NULL CHECK (trim(cor) <> ''),
           quantidade    INTEGER NOT NULL DEFAULT 0 CHECK (quantidade >= 0),
           limite_baixo  INTEGER NOT NULL DEFAULT 5 CHECK (limite_baixo >= 0),
           ativo         INTEGER NOT NULL DEFAULT 1 CHECK (ativo IN (0, 1)),
           excluido      INTEGER NOT NULL DEFAULT 0 CHECK (excluido IN (0, 1)),
           -- Só um item desativado pode estar excluído
           CHECK (excluido = 0 OR ativo = 0)
       )""",
    """CREATE TABLE rolos_tecido (
           id              INTEGER PRIMARY KEY AUTOINCREMENT,
           -- O código é CALCULADO pelo banco a partir do id (id 42 -> RL-000042):
           -- não tem como ficar vazio, repetido ou diferente do número do rolo.
           codigo          TEXT GENERATED ALWAYS AS ('RL-' || printf('%06d', id)) STORED UNIQUE,
           tipo_tecido     TEXT    NOT NULL CHECK (trim(tipo_tecido) <> ''),
           cor             TEXT    NOT NULL CHECK (trim(cor) <> ''),
           metragem_atual  REAL    NOT NULL DEFAULT 0 CHECK (metragem_atual >= 0),
           limite_baixo    REAL    NOT NULL DEFAULT 3.0 CHECK (limite_baixo >= 0),
           ativo           INTEGER NOT NULL DEFAULT 1 CHECK (ativo IN (0, 1)),
           excluido        INTEGER NOT NULL DEFAULT 0 CHECK (excluido IN (0, 1)),
           CHECK (excluido = 0 OR ativo = 0)
       )""",
    """CREATE TABLE usuarios (
           id          INTEGER PRIMARY KEY AUTOINCREMENT,
           nome        TEXT    NOT NULL CHECK (trim(nome) <> ''),
           login       TEXT    NOT NULL UNIQUE CHECK (trim(login) <> ''),
           senha_hash  TEXT    NOT NULL,   -- nunca a senha em si (ver usuarios.py)
           perfil      TEXT    NOT NULL CHECK (perfil IN ('admin', 'operador')),
           ativo       INTEGER NOT NULL DEFAULT 1 CHECK (ativo IN (0, 1)),
           master      INTEGER NOT NULL DEFAULT 0 CHECK (master IN (0, 1)),
           -- O master é sempre um administrador ativo
           CHECK (master = 0 OR (perfil = 'admin' AND ativo = 1))
       )""",
    f"""CREATE TABLE movimentacoes (
           id           INTEGER PRIMARY KEY AUTOINCREMENT,
           tipo_item    TEXT NOT NULL CHECK (tipo_item IN ('produto', 'rolo')),
           -- Aponta para produtos.codigo OU rolos_tecido.codigo, conforme tipo_item.
           -- Uma chave estrangeira só aponta para UMA tabela, então quem garante
           -- esta ligação são os gatilhos (triggers) criados mais abaixo.
           codigo_item  TEXT NOT NULL,
           tipo         TEXT NOT NULL CHECK (tipo IN ('entrada', 'saida')),
           quantidade   REAL NOT NULL CHECK (quantidade > 0),
           data         TEXT NOT NULL      -- 'AAAA-MM-DD HH:MM:SS'
                        CHECK (data GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9] [0-2][0-9]:[0-5][0-9]:[0-5][0-9]'),
           motivo       TEXT NOT NULL CHECK (motivo IN {_MOTIVOS_V2}),
           -- Chave estrangeira: o login precisa existir em usuarios.
           -- (Vazio só nas movimentações de antes de existir login.)
           usuario      TEXT REFERENCES usuarios (login) ON UPDATE RESTRICT ON DELETE RESTRICT,
           -- Pijama é contado em unidades inteiras
           CHECK (tipo_item = 'rolo' OR quantidade = CAST(quantidade AS INTEGER))
       )""",
]

_INDICES_V2 = [
    "CREATE INDEX idx_mov_codigo ON movimentacoes (codigo_item)",
    "CREATE INDEX idx_mov_data   ON movimentacoes (data)",
    "CREATE INDEX idx_mov_usuario ON movimentacoes (usuario)",
    # O mesmo pijama não pode existir duas vezes ("Floral" e "floral" contam como iguais).
    # WHERE excluido = 0: depois de excluir um pijama, dá para cadastrar a mesma
    # combinação de novo (com outro código, já que o antigo continua reservado).
    """CREATE UNIQUE INDEX idx_produto_unico ON produtos
           (modelo COLLATE NOCASE, tamanho COLLATE NOCASE, cor COLLATE NOCASE)
           WHERE excluido = 0""",
    # Só pode existir um master
    "CREATE UNIQUE INDEX idx_um_master ON usuarios (master) WHERE master = 1",
]

# Gatilho (trigger) = um comando que o banco roda sozinho antes de um INSERT,
# UPDATE ou DELETE. RAISE(ABORT, ...) cancela o comando com essa mensagem.
_GATILHOS_V2 = [
    # --- Histórico: toda movimentação aponta para um item ativo que existe ---
    """CREATE TRIGGER mov_item_precisa_existir BEFORE INSERT ON movimentacoes
       WHEN NOT EXISTS (SELECT 1 FROM produtos
                        WHERE NEW.tipo_item = 'produto' AND codigo = NEW.codigo_item AND ativo = 1)
        AND NOT EXISTS (SELECT 1 FROM rolos_tecido
                        WHERE NEW.tipo_item = 'rolo' AND codigo = NEW.codigo_item AND ativo = 1)
       BEGIN SELECT RAISE(ABORT, 'Movimentação de um item que não existe ou está desativado.'); END""",
    # --- Histórico: o que foi gravado não muda nem some (correção = ajuste de inventário) ---
    """CREATE TRIGGER mov_nao_pode_mudar BEFORE UPDATE ON movimentacoes
       BEGIN SELECT RAISE(ABORT, 'O histórico não pode ser alterado. Corrija com um ajuste de inventário.'); END""",
    """CREATE TRIGGER mov_nao_pode_ser_apagada BEFORE DELETE ON movimentacoes
       BEGIN SELECT RAISE(ABORT, 'O histórico não pode ser apagado.'); END""",
    # --- Itens: o código não muda e o item nunca é apagado de verdade ---
    """CREATE TRIGGER produto_codigo_fixo BEFORE UPDATE OF codigo ON produtos
       WHEN NEW.codigo IS NOT OLD.codigo
       BEGIN SELECT RAISE(ABORT, 'O código de um pijama não pode mudar: ele está nas etiquetas.'); END""",
    """CREATE TRIGGER rolo_numero_fixo BEFORE UPDATE OF id ON rolos_tecido
       WHEN NEW.id IS NOT OLD.id
       BEGIN SELECT RAISE(ABORT, 'O número de um rolo não pode mudar: ele está na etiqueta.'); END""",
    """CREATE TRIGGER produto_nao_pode_ser_apagado BEFORE DELETE ON produtos
       BEGIN SELECT RAISE(ABORT, 'Pijama não é apagado do banco: use Excluir (ele fica marcado como excluído).'); END""",
    """CREATE TRIGGER rolo_nao_pode_ser_apagado BEFORE DELETE ON rolos_tecido
       BEGIN SELECT RAISE(ABORT, 'Rolo não é apagado do banco: use Excluir (ele fica marcado como excluído).'); END""",
    # --- Item excluído é definitivo: não volta nem muda ---
    """CREATE TRIGGER produto_excluido_e_definitivo BEFORE UPDATE ON produtos
       WHEN OLD.excluido = 1
       BEGIN SELECT RAISE(ABORT, 'Este pijama foi excluído e não pode ser alterado.'); END""",
    """CREATE TRIGGER rolo_excluido_e_definitivo BEFORE UPDATE ON rolos_tecido
       WHEN OLD.excluido = 1
       BEGIN SELECT RAISE(ABORT, 'Este rolo foi excluído e não pode ser alterado.'); END""",
    # --- Usuários: o login não muda e ninguém é apagado (só desativado) ---
    """CREATE TRIGGER usuario_login_fixo BEFORE UPDATE OF login ON usuarios
       WHEN NEW.login IS NOT OLD.login
       BEGIN SELECT RAISE(ABORT, 'O login de um usuário não pode mudar.'); END""",
    """CREATE TRIGGER usuario_nao_pode_ser_apagado BEFORE DELETE ON usuarios
       BEGIN SELECT RAISE(ABORT, 'Usuário não é apagado: desative-o.'); END""",
]


def _migracao_2(conexao):
    _conferir_antes_da_migracao_2(conexao)

    # Guarda o último número usado por tabela (AUTOINCREMENT). Assim, o próximo
    # rolo continua do número certo, mesmo que rolos antigos tenham sido apagados.
    ultimos_ids = {
        linha["name"]: linha["seq"] for linha in conexao.execute("SELECT name, seq FROM sqlite_sequence")
    }

    # 1) Renomeia as tabelas antigas e cria as novas com as regras
    for tabela in ("produtos", "rolos_tecido", "usuarios", "movimentacoes"):
        conexao.execute(f"ALTER TABLE {tabela} RENAME TO {tabela}_antiga")
    for sql in _TABELAS_V2:
        conexao.execute(sql)

    # 2) Copia os dados. COALESCE completa valores vazios de bancos muito antigos.
    conexao.execute("""
        INSERT INTO produtos (id, codigo, modelo, tamanho, cor, quantidade, limite_baixo, ativo)
        SELECT id, codigo, modelo, tamanho, cor, COALESCE(quantidade, 0),
               COALESCE(limite_baixo, 5), COALESCE(ativo, 1)
        FROM produtos_antiga""")
    conexao.execute("""
        INSERT INTO rolos_tecido (id, tipo_tecido, cor, metragem_atual, limite_baixo, ativo)
        SELECT id, tipo_tecido, cor, COALESCE(metragem_atual, 0),
               COALESCE(limite_baixo, 3.0), COALESCE(ativo, 1)
        FROM rolos_tecido_antiga""")
    conexao.execute("""
        INSERT INTO usuarios (id, nome, login, senha_hash, perfil, ativo, master)
        SELECT id, nome, login, senha_hash, perfil, COALESCE(ativo, 1), COALESCE(master, 0)
        FROM usuarios_antiga""")

    # 3) Itens que as versões antigas APAGARAM de verdade, mas que têm histórico:
    #    voltam como "excluídos" (com os dados que sobraram), para que toda
    #    movimentação aponte para um item. O saldo é o que o histórico soma.
    conexao.execute("""
        INSERT INTO produtos (codigo, modelo, tamanho, cor, quantidade, ativo, excluido)
        SELECT codigo_item, 'desconhecido', '?', '?',
               MAX(0, CAST(SUM(CASE tipo WHEN 'entrada' THEN quantidade ELSE -quantidade END) AS INTEGER)),
               0, 1
        FROM movimentacoes_antiga
        WHERE tipo_item = 'produto' AND codigo_item NOT IN (SELECT codigo FROM produtos)
        GROUP BY codigo_item""")
    conexao.execute("""
        INSERT INTO rolos_tecido (id, tipo_tecido, cor, metragem_atual, ativo, excluido)
        SELECT CAST(substr(codigo_item, 4) AS INTEGER), 'desconhecido', '?',
               MAX(0, ROUND(SUM(CASE tipo WHEN 'entrada' THEN quantidade ELSE -quantidade END), 2)),
               0, 1
        FROM movimentacoes_antiga
        WHERE tipo_item = 'rolo' AND codigo_item NOT IN (SELECT codigo FROM rolos_tecido)
        GROUP BY codigo_item""")

    # 4) Copia o histórico (os gatilhos ainda não existem, então nada é barrado aqui;
    #    a conferência do passo 6 garante que tudo ficou ligado certo)
    conexao.execute("""
        INSERT INTO movimentacoes (id, tipo_item, codigo_item, tipo, quantidade, data, motivo, usuario)
        SELECT id, tipo_item, codigo_item, tipo, quantidade, data, motivo, usuario
        FROM movimentacoes_antiga""")

    # 5) Apaga as tabelas antigas e cria índices e gatilhos
    for tabela in ("movimentacoes", "produtos", "rolos_tecido", "usuarios"):
        conexao.execute(f"DROP TABLE {tabela}_antiga")
    for sql in _INDICES_V2 + _GATILHOS_V2:
        conexao.execute(sql)
    for tabela, ultimo in ultimos_ids.items():
        # Se a tabela nova ficou vazia, ela ainda não tem linha em sqlite_sequence
        conexao.execute(
            "INSERT INTO sqlite_sequence (name, seq) SELECT ?, 0 "
            "WHERE NOT EXISTS (SELECT 1 FROM sqlite_sequence WHERE name = ?)",
            (tabela, tabela),
        )
        conexao.execute("UPDATE sqlite_sequence SET seq = MAX(seq, ?) WHERE name = ?", (ultimo, tabela))

    # 6) Confere se nenhum dado ficou de fora ou solto
    _conferir_ligacoes(conexao)


def _conferir_antes_da_migracao_2(conexao):
    """Problemas que a migração não pode resolver sozinha sem arriscar o estoque.
    Se houver algum, ela para ANTES de mudar qualquer coisa e explica o que fazer."""
    repetidos = conexao.execute("""
        SELECT group_concat(codigo, ', ') AS codigos
        FROM produtos
        GROUP BY lower(trim(modelo)), lower(trim(tamanho)), lower(trim(cor))
        HAVING COUNT(*) > 1""").fetchall()
    if repetidos:
        lista = "; ".join(linha["codigos"] for linha in repetidos)
        raise ErroMigracao(
            f"Há pijamas cadastrados em dobro (mesmo modelo, tamanho e cor): {lista}. "
            "Na versão anterior do sistema, passe o saldo para um deles com ajuste "
            "de inventário, desative e exclua o outro, e abra o sistema novo de novo."
        )

    rolos_com_codigo_errado = conexao.execute(
        "SELECT codigo FROM rolos_tecido WHERE codigo IS NOT 'RL-' || printf('%06d', id)"
    ).fetchall()
    if rolos_com_codigo_errado:
        lista = ", ".join(str(linha["codigo"]) for linha in rolos_com_codigo_errado)
        raise ErroMigracao(f"Rolos com código diferente do número: {lista}.")


def _conferir_ligacoes(conexao):
    """Levanta ErroMigracao se alguma ligação entre tabelas estiver quebrada."""
    soltas = conexao.execute("PRAGMA foreign_key_check").fetchall()
    if soltas:
        raise ErroMigracao(f"Movimentações de usuários que não existem: {len(soltas)} linha(s).")
    sem_item = conexao.execute("""
        SELECT COUNT(*) FROM movimentacoes m
        WHERE NOT EXISTS (SELECT 1 FROM produtos p WHERE m.tipo_item = 'produto' AND p.codigo = m.codigo_item)
          AND NOT EXISTS (SELECT 1 FROM rolos_tecido r WHERE m.tipo_item = 'rolo' AND r.codigo = m.codigo_item)
    """).fetchone()[0]
    if sem_item:
        raise ErroMigracao(f"Movimentações sem item: {sem_item} linha(s).")


# =====================================================================
# A lista de migrações e quem roda elas
# =====================================================================

# Número da versão -> função que leva o banco da versão anterior até ela.
# Para mudar a estrutura no futuro: escreva _migracao_3 e acrescente aqui.
MIGRACOES = {
    1: _migracao_1,
    2: _migracao_2,
}
VERSAO_ATUAL = max(MIGRACOES)


def versao_do_banco():
    conexao = banco.conectar()
    try:
        return conexao.execute("PRAGMA user_version").fetchone()[0]
    finally:
        conexao.close()


def atualizar_banco():
    """Leva o banco até VERSAO_ATUAL. É chamada sempre que o sistema inicia
    (pelo banco.criar_tabelas). Se já estiver atualizado, não faz nada."""
    conexao = banco.conectar()
    try:
        # Modo WAL: os computadores LEEM o banco enquanto outro está GRAVANDO.
        # Fica gravado no arquivo, então basta ligar uma vez.
        conexao.execute("PRAGMA journal_mode = WAL")
        versao = conexao.execute("PRAGMA user_version").fetchone()[0]
        tem_dados = conexao.execute("SELECT COUNT(*) FROM sqlite_master WHERE type = 'table'").fetchone()[0] > 0
    finally:
        conexao.close()

    if versao > VERSAO_ATUAL:
        raise ErroMigracao(
            f"O banco é da versão {versao}, mais nova que este sistema (versão {VERSAO_ATUAL}). "
            "Atualize o sistema (git pull) antes de abrir."
        )
    if versao == VERSAO_ATUAL:
        return

    if tem_dados:
        import backup  # importado aqui porque o backup.py também importa o banco.py
        nome = backup.fazer_backup()
        print(f"Backup feito antes de atualizar o banco: {nome}")

    for numero in range(versao + 1, VERSAO_ATUAL + 1):
        _aplicar(numero)


def _aplicar(numero):
    """Roda UMA migração numa transação. Se der qualquer erro, desfaz tudo."""
    # isolation_level=None: nós mesmos abrimos e fechamos a transação (BEGIN/COMMIT).
    # Sem isso, o Python salvaria sozinho no meio, antes de alguns comandos.
    conexao = sqlite3.connect(banco.CAMINHO_BANCO, timeout=10, isolation_level=None)
    conexao.row_factory = sqlite3.Row
    try:
        # As chaves estrangeiras ficam desligadas DURANTE a troca das tabelas
        # (é o procedimento indicado pelo SQLite); a conferência é feita no fim.
        conexao.execute("PRAGMA foreign_keys = OFF")
        # IMMEDIATE: trava o banco para escrita desde já. Se dois processos
        # iniciarem juntos, o segundo espera e depois vê que já foi feito.
        conexao.execute("BEGIN IMMEDIATE")
        if conexao.execute("PRAGMA user_version").fetchone()[0] >= numero:
            conexao.execute("ROLLBACK")
            return
        MIGRACOES[numero](conexao)
        conexao.execute(f"PRAGMA user_version = {int(numero)}")
        conexao.execute("COMMIT")
    except Exception:
        if conexao.in_transaction:
            conexao.execute("ROLLBACK")
        raise
    finally:
        conexao.close()
