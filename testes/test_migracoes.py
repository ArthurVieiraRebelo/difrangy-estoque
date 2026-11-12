"""Testes da atualização de bancos antigos (migracoes.py).

Cada teste monta, num arquivo temporário, um banco IGUAL ao de uma versão
antiga do sistema (user_version = 0) e confere se a atualização preserva
todos os dados e deixa as regras novas valendo.
"""

import sqlite3
import unittest
from pathlib import Path

import backup
import banco
import migracoes
import usuarios
from testes import ADMIN, SENHA_PADRAO, TesteComBancoLimpo

# Estrutura do banco real da fábrica antes do controle de versão
# (copiada do estoque.db em 2026-11-12, sem os dados).
ESTRUTURA_ANTES_DO_CONTROLE_DE_VERSAO = """
    CREATE TABLE produtos (
        id INTEGER PRIMARY KEY AUTOINCREMENT, codigo TEXT NOT NULL UNIQUE,
        modelo TEXT NOT NULL, tamanho TEXT NOT NULL, cor TEXT NOT NULL,
        quantidade INTEGER NOT NULL DEFAULT 0 CHECK (quantidade >= 0),
        ativo INTEGER NOT NULL DEFAULT 1,
        limite_baixo INTEGER NOT NULL DEFAULT 5 CHECK (limite_baixo >= 0));
    CREATE TABLE rolos_tecido (
        id INTEGER PRIMARY KEY AUTOINCREMENT, codigo TEXT UNIQUE,
        tipo_tecido TEXT NOT NULL, cor TEXT NOT NULL,
        metragem_atual REAL NOT NULL DEFAULT 0 CHECK (metragem_atual >= 0),
        ativo INTEGER NOT NULL DEFAULT 1,
        limite_baixo REAL NOT NULL DEFAULT 3.0 CHECK (limite_baixo >= 0));
    CREATE TABLE movimentacoes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tipo_item TEXT NOT NULL CHECK (tipo_item IN ('produto', 'rolo')),
        codigo_item TEXT NOT NULL,
        tipo TEXT NOT NULL CHECK (tipo IN ('entrada', 'saida')),
        quantidade REAL NOT NULL CHECK (quantidade > 0),
        data TEXT NOT NULL, motivo TEXT NOT NULL, usuario TEXT);
    CREATE TABLE usuarios (
        id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT NOT NULL,
        login TEXT NOT NULL UNIQUE, senha_hash TEXT NOT NULL,
        perfil TEXT NOT NULL CHECK (perfil IN ('admin', 'operador')),
        ativo INTEGER NOT NULL DEFAULT 1, master INTEGER NOT NULL DEFAULT 0);
    CREATE TABLE configuracoes (chave TEXT PRIMARY KEY, valor TEXT NOT NULL);
    CREATE INDEX idx_mov_codigo ON movimentacoes (codigo_item);
    CREATE INDEX idx_mov_data ON movimentacoes (data);
"""

# Dados parecidos com os do banco real (dois pijamas Liga, um master)
DADOS_DO_BANCO_REAL = """
    INSERT INTO usuarios (id, nome, login, senha_hash, perfil, ativo, master)
        VALUES (1, 'Arthur', 'arthur_vieira', 'hash', 'admin', 1, 1);
    INSERT INTO produtos (id, codigo, modelo, tamanho, cor, quantidade, ativo, limite_baixo)
        VALUES (1, 'PJ-LIG-G-AZ', 'Liga', 'G', 'Azul', 2, 1, 5),
               (2, 'PJ-LIG-M-AZ', 'Liga', 'M', 'Azul', 5, 1, 8);
    INSERT INTO rolos_tecido (id, codigo, tipo_tecido, cor, metragem_atual, ativo, limite_baixo)
        VALUES (1, 'RL-000001', 'Malha', 'Azul', 47.5, 1, 3.0);
    INSERT INTO movimentacoes (tipo_item, codigo_item, tipo, quantidade, data, motivo, usuario) VALUES
        ('produto', 'PJ-LIG-G-AZ', 'entrada', 3, '2026-11-11 10:00:00', 'estoque_inicial', 'arthur_vieira'),
        ('produto', 'PJ-LIG-G-AZ', 'saida',   1, '2026-11-11 11:00:00', 'venda',           'arthur_vieira'),
        ('produto', 'PJ-LIG-M-AZ', 'entrada', 5, '2026-11-11 10:05:00', 'estoque_inicial', 'arthur_vieira'),
        ('rolo',    'RL-000001',   'entrada', 50, '2026-11-11 10:10:00', 'rolo_novo',      'arthur_vieira'),
        ('rolo',    'RL-000001',   'saida',  2.5, '2026-11-11 12:00:00', 'corte',          'arthur_vieira');
    INSERT INTO configuracoes VALUES ('etiqueta_qr', '0');
"""


class TesteComBancoAntigo(TesteComBancoLimpo):
    """Troca o banco do teste por um arquivo novo, ainda sem nada."""

    def setUp(self):
        super().setUp()
        banco.CAMINHO_BANCO = Path(self.pasta_temporaria.name) / "antigo.db"

    def montar_banco_antigo(self, sql):
        conexao = sqlite3.connect(banco.CAMINHO_BANCO)
        conexao.executescript(sql)
        conexao.close()

    def tabela(self, sql):
        return [tuple(linha.values()) for linha in banco.consultar(sql)]


class TesteAtualizacaoDoBancoReal(TesteComBancoAntigo):

    def setUp(self):
        super().setUp()
        self.montar_banco_antigo(ESTRUTURA_ANTES_DO_CONTROLE_DE_VERSAO + DADOS_DO_BANCO_REAL)
        banco.criar_tabelas()  # é o que acontece quando o sistema novo inicia

    def test_chega_na_versao_atual(self):
        self.assertEqual(migracoes.versao_do_banco(), migracoes.VERSAO_ATUAL)

    def test_nenhum_dado_se_perde(self):
        self.assertEqual(self.tabela("SELECT id, codigo, modelo, tamanho, cor, quantidade, ativo, limite_baixo, excluido FROM produtos ORDER BY id"), [
            (1, "PJ-LIG-G-AZ", "Liga", "G", "Azul", 2, 1, 5, 0),
            (2, "PJ-LIG-M-AZ", "Liga", "M", "Azul", 5, 1, 8, 0),
        ])
        self.assertEqual(self.tabela("SELECT id, codigo, tipo_tecido, metragem_atual, limite_baixo FROM rolos_tecido"),
                         [(1, "RL-000001", "Malha", 47.5, 3.0)])
        self.assertEqual(self.tabela("SELECT login, perfil, master FROM usuarios"), [("arthur_vieira", "admin", 1)])
        self.assertEqual(len(banco.listar_movimentacoes(limite=-1)), 5)
        self.assertEqual(self.tabela("SELECT * FROM configuracoes"), [("etiqueta_qr", "0")])

    def test_backup_feito_antes_de_atualizar(self):
        backups = backup.listar_backups()
        self.assertEqual(len(backups), 1)
        # O backup é o banco ANTIGO, do jeito que estava
        copia = sqlite3.connect(backup.PASTA_BACKUPS / backups[0]["nome"])
        self.assertEqual(copia.execute("PRAGMA user_version").fetchone()[0], 0)
        self.assertEqual(copia.execute("SELECT COUNT(*) FROM movimentacoes").fetchone()[0], 5)
        copia.close()

    def test_conferencia_sem_problemas(self):
        self.assertEqual(banco.verificar_integridade(), [])

    def test_sistema_continua_funcionando(self):
        usuario = {"login": "arthur_vieira", "perfil": "admin"}
        item = banco.registrar_movimentacao("PJ-LIG-M-AZ", "saida", "1", "venda", usuario)
        self.assertEqual(item["saldo"], 4)
        self.assertEqual(banco.cadastrar_rolo("Seda", "Branco", "10", usuario), "RL-000002")
        self.assertEqual(banco.cadastrar_produto("Liga", "P", "Azul", "1", usuario), "PJ-LIG-P-AZ")

    def test_regras_novas_valem_no_banco_atualizado(self):
        usuario = {"login": "arthur_vieira", "perfil": "admin"}
        with self.assertRaises(banco.ErroEstoque):
            banco.cadastrar_produto("liga", "m", "AZUL", "1", usuario, codigo="PJ-OUTRO")
        with self.assertRaises(sqlite3.IntegrityError):
            banco.executar("DELETE FROM movimentacoes")

    def test_abrir_de_novo_nao_faz_nada(self):
        banco.criar_tabelas()
        banco.criar_tabelas()
        self.assertEqual(len(backup.listar_backups()), 1)  # nenhum backup a mais
        self.assertEqual(len(banco.listar_movimentacoes(limite=-1)), 5)


class TesteAtualizacaoDeVersoesMaisAntigas(TesteComBancoAntigo):

    def test_banco_da_primeira_versao(self):
        # Sem ativo, sem limite, sem usuários nas movimentações, sem master
        self.montar_banco_antigo("""
            CREATE TABLE produtos (id INTEGER PRIMARY KEY, codigo TEXT UNIQUE, modelo TEXT,
                                   tamanho TEXT, cor TEXT, quantidade INTEGER);
            CREATE TABLE movimentacoes (id INTEGER PRIMARY KEY, tipo_item TEXT, codigo_item TEXT,
                                        tipo TEXT, quantidade REAL, data TEXT, motivo TEXT);
            INSERT INTO produtos VALUES (1, 'PJ-VEL-M-AZ', 'Velho', 'M', 'Azul', 4);
            INSERT INTO movimentacoes VALUES
                (1, 'produto', 'PJ-VEL-M-AZ', 'entrada', 4, '2026-01-02 08:00:00', 'estoque_inicial');
        """)
        banco.criar_tabelas()

        produto = banco.buscar_produto("PJ-VEL-M-AZ")
        self.assertEqual((produto["ativo"], produto["limite_baixo"]), (1, 5))
        self.assertIsNone(banco.listar_movimentacoes()[0]["usuario"])  # de antes do login
        self.assertEqual(banco.verificar_integridade(), [])
        # A movimentação precisa ser de um usuário que existe (esse banco não tinha nenhum)
        usuarios.criar_usuario("Dona", "dona", SENHA_PADRAO, "admin", master=True)
        item = banco.registrar_movimentacao("PJ-VEL-M-AZ", "saida", "1", "venda", {"login": "dona", "perfil": "admin"})
        self.assertEqual(item["saldo"], 3)
        with self.assertRaises(sqlite3.IntegrityError):  # e "admin" não existe neste banco
            banco.registrar_movimentacao("PJ-VEL-M-AZ", "saida", "1", "venda", ADMIN)

    def test_admin_mais_antigo_vira_master(self):
        self.montar_banco_antigo("""
            CREATE TABLE usuarios (id INTEGER PRIMARY KEY, nome TEXT, login TEXT UNIQUE,
                                   senha_hash TEXT, perfil TEXT, ativo INTEGER DEFAULT 1);
            INSERT INTO usuarios VALUES (1, 'Op', 'op', 'x', 'operador', 1);
            INSERT INTO usuarios VALUES (2, 'Dono', 'dono', 'x', 'admin', 1);
            INSERT INTO usuarios VALUES (3, 'Outro', 'outro', 'x', 'admin', 1);
        """)
        banco.criar_tabelas()
        self.assertEqual(banco.consultar("SELECT login FROM usuarios WHERE master = 1"), [{"login": "dono"}])

    def test_item_apagado_pela_versao_antiga_volta_como_excluido(self):
        # As versões antigas apagavam o item de verdade e deixavam o histórico "solto"
        self.montar_banco_antigo(ESTRUTURA_ANTES_DO_CONTROLE_DE_VERSAO + """
            INSERT INTO usuarios (nome, login, senha_hash, perfil, master) VALUES ('A', 'a', 'h', 'admin', 1);
            INSERT INTO rolos_tecido (id, codigo, tipo_tecido, cor, metragem_atual)
                VALUES (1, 'RL-000001', 'Malha', 'Azul', 10);
            INSERT INTO movimentacoes (tipo_item, codigo_item, tipo, quantidade, data, motivo, usuario) VALUES
                ('rolo', 'RL-000001', 'entrada', 10, '2026-11-01 08:00:00', 'rolo_novo', 'a'),
                ('produto', 'PJ-ANT-M-AZ', 'entrada', 3, '2026-11-01 08:00:00', 'estoque_inicial', 'a'),
                ('produto', 'PJ-ANT-M-AZ', 'saida', 3, '2026-11-02 08:00:00', 'venda', 'a'),
                ('rolo', 'RL-000002', 'entrada', 5, '2026-11-01 08:00:00', 'rolo_novo', 'a'),
                ('rolo', 'RL-000002', 'saida', 1.5, '2026-11-02 08:00:00', 'corte', 'a');
            UPDATE sqlite_sequence SET seq = 2 WHERE name = 'rolos_tecido';
        """)
        banco.criar_tabelas()

        self.assertEqual(banco.verificar_integridade(), [])
        excluidos = self.tabela("SELECT codigo, quantidade, ativo, excluido FROM produtos")
        self.assertEqual(excluidos, [("PJ-ANT-M-AZ", 0, 0, 1)])
        self.assertEqual(self.tabela("SELECT codigo, metragem_atual, excluido FROM rolos_tecido ORDER BY id"),
                         [("RL-000001", 10.0, 0), ("RL-000002", 3.5, 1)])
        # Somem das telas, mas o histórico e os relatórios continuam com eles
        self.assertIsNone(banco.buscar_item("RL-000002"))
        self.assertEqual(len(banco.listar_movimentacoes(codigo="PJ-ANT-M-AZ")), 2)
        self.assertIn(("2026-11", "desconhecido", "?", 1.5),
                      [tuple(c.values()) for c in banco.relatorio_consumo_tecido_por_mes()])
        # O número de um rolo apagado nunca é reaproveitado
        self.assertEqual(banco.cadastrar_rolo("Seda", "Branco", "1", {"login": "a"}), "RL-000003")

    def test_pijama_em_dobro_impede_a_atualizacao_sem_mexer_em_nada(self):
        self.montar_banco_antigo(ESTRUTURA_ANTES_DO_CONTROLE_DE_VERSAO + """
            INSERT INTO produtos (codigo, modelo, tamanho, cor, quantidade)
                VALUES ('PJ-FLO-M-AZ', 'Floral', 'M', 'Azul', 2), ('PJ-FLORAL', 'floral', 'm', 'azul', 1);
        """)
        with self.assertRaises(migracoes.ErroMigracao) as contexto:
            banco.criar_tabelas()
        self.assertIn("PJ-FLO-M-AZ, PJ-FLORAL", str(contexto.exception))
        # A migração 1 (que não muda regras) foi salva; a 2 foi desfeita inteira
        self.assertEqual(migracoes.versao_do_banco(), 1)
        colunas = [linha["name"] for linha in banco.consultar("PRAGMA table_info(produtos)")]
        self.assertNotIn("excluido", colunas)
        self.assertEqual(len(banco.consultar("SELECT * FROM produtos")), 2)

    def test_erro_no_meio_da_migracao_desfaz_tudo(self):
        self.montar_banco_antigo(ESTRUTURA_ANTES_DO_CONTROLE_DE_VERSAO + DADOS_DO_BANCO_REAL)
        original = migracoes.MIGRACOES[2]

        def migracao_que_quebra_no_meio(conexao):
            conexao.execute("DELETE FROM movimentacoes")  # estraga...
            raise RuntimeError("falha simulada")           # ...e quebra antes de terminar

        migracoes.MIGRACOES[2] = migracao_que_quebra_no_meio
        try:
            with self.assertRaises(RuntimeError):
                banco.criar_tabelas()
        finally:
            migracoes.MIGRACOES[2] = original

        self.assertEqual(len(banco.consultar("SELECT * FROM movimentacoes")), 5)  # nada se perdeu
        banco.criar_tabelas()  # da próxima vez, com a migração certa, funciona
        self.assertEqual(migracoes.versao_do_banco(), migracoes.VERSAO_ATUAL)
        self.assertEqual(banco.verificar_integridade(), [])

    def test_banco_de_versao_mais_nova_e_recusado(self):
        self.montar_banco_antigo("PRAGMA user_version = 99;")
        with self.assertRaises(migracoes.ErroMigracao):
            banco.criar_tabelas()

    def test_banco_novo_nao_faz_backup(self):
        banco.criar_tabelas()
        self.assertEqual(migracoes.versao_do_banco(), migracoes.VERSAO_ATUAL)
        self.assertEqual(backup.listar_backups(), [])


if __name__ == "__main__":
    unittest.main()
