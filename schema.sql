CREATE TABLE produtos (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                codigo      TEXT    NOT NULL UNIQUE,
                modelo      TEXT    NOT NULL,
                tamanho     TEXT    NOT NULL,
                cor         TEXT    NOT NULL,
                quantidade  INTEGER NOT NULL DEFAULT 0 CHECK (quantidade >= 0),
                ativo       INTEGER NOT NULL DEFAULT 1   -- 1 = ativo, 0 = desativado
            );
CREATE TABLE sqlite_sequence(name,seq);
CREATE TABLE rolos_tecido (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                codigo          TEXT    UNIQUE,  -- preenchido logo após o INSERT (RL-000001)
                tipo_tecido     TEXT    NOT NULL,
                cor             TEXT    NOT NULL,
                metragem_atual  REAL    NOT NULL DEFAULT 0 CHECK (metragem_atual >= 0),
                ativo           INTEGER NOT NULL DEFAULT 1
            );
CREATE TABLE movimentacoes (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                tipo_item    TEXT NOT NULL CHECK (tipo_item IN ('produto', 'rolo')),
                codigo_item  TEXT NOT NULL,
                tipo         TEXT NOT NULL CHECK (tipo IN ('entrada', 'saida')),
                quantidade   REAL NOT NULL CHECK (quantidade > 0),
                data         TEXT NOT NULL,  -- formato 'AAAA-MM-DD HH:MM:SS'
                motivo       TEXT NOT NULL,
                usuario      TEXT            -- login de quem fez a movimentação
            );
CREATE TABLE usuarios (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                nome        TEXT    NOT NULL,
                login       TEXT    NOT NULL UNIQUE,
                senha_hash  TEXT    NOT NULL,   -- nunca a senha em si (ver usuarios.py)
                perfil      TEXT    NOT NULL CHECK (perfil IN ('admin', 'operador')),
                ativo       INTEGER NOT NULL DEFAULT 1
            );
CREATE INDEX idx_mov_codigo ON movimentacoes (codigo_item);
CREATE INDEX idx_mov_data   ON movimentacoes (data);
