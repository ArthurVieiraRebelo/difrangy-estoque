"""Testes das regras que o PRÓPRIO BANCO garante (ver migracoes.py, migração 2).

Aqui o SQL vai direto para o banco, sem passar pelas validações do banco.py.
É o que aconteceria se um dia o código tivesse um erro ou alguém mexesse no
arquivo por fora: mesmo assim, o banco precisa recusar dados errados.
"""

import sqlite3
import unittest

import banco
import usuarios
from testes import ADMIN, SENHA_PADRAO, TesteComBancoLimpo, TesteComCliente


class TesteRegrasDoBanco(TesteComBancoLimpo):

    def setUp(self):
        super().setUp()
        self.pijama = banco.cadastrar_produto("Floral", "M", "Azul", "10", ADMIN)   # PJ-FLO-M-AZ
        self.rolo = banco.cadastrar_rolo("Malha", "Azul", "50", ADMIN)              # RL-000001

    def assert_recusado(self, sql, parametros=()):
        with self.assertRaises(sqlite3.IntegrityError):
            banco.executar(sql, parametros)

    # ---------- Pijama repetido ----------

    def test_mesmo_pijama_duas_vezes_e_recusado(self):
        for modelo, tamanho, cor in [("Floral", "M", "Azul"), ("floral", "m", "AZUL")]:
            with self.subTest(modelo=modelo):
                self.assert_recusado(
                    "INSERT INTO produtos (codigo, modelo, tamanho, cor) VALUES ('PJ-OUTRO', ?, ?, ?)",
                    (modelo, tamanho, cor))

    def test_mesmo_pijama_pode_voltar_depois_de_excluido(self):
        banco.definir_item_ativo(self.pijama, False)
        banco.excluir_item(self.pijama)
        self.assertEqual(banco.cadastrar_produto("Floral", "M", "Azul", "0", ADMIN, codigo="PJ-FLO-M-AZ2"),
                         "PJ-FLO-M-AZ2")

    # ---------- Ligação movimentação -> item e usuário ----------

    def test_movimentacao_de_item_que_nao_existe(self):
        for tipo_item, codigo in [("produto", "PJ-NAO-EXISTE"), ("rolo", "RL-999999"),
                                  ("rolo", self.pijama), ("produto", self.rolo)]:  # tipo trocado
            with self.subTest(codigo=codigo):
                self.assert_recusado(
                    "INSERT INTO movimentacoes (tipo_item, codigo_item, tipo, quantidade, data, motivo, usuario) "
                    "VALUES (?, ?, 'entrada', 1, '2026-11-12 10:00:00', 'ajuste', 'admin')",
                    (tipo_item, codigo))

    def test_movimentacao_de_item_desativado(self):
        banco.definir_item_ativo(self.pijama, False)
        self.assert_recusado(
            "INSERT INTO movimentacoes (tipo_item, codigo_item, tipo, quantidade, data, motivo, usuario) "
            "VALUES ('produto', ?, 'saida', 1, '2026-11-12 10:00:00', 'venda', 'admin')", (self.pijama,))

    def test_movimentacao_de_usuario_que_nao_existe(self):
        self.assert_recusado(
            "INSERT INTO movimentacoes (tipo_item, codigo_item, tipo, quantidade, data, motivo, usuario) "
            "VALUES ('produto', ?, 'entrada', 1, '2026-11-12 10:00:00', 'producao', 'fantasma')", (self.pijama,))

    # ---------- O histórico não muda ----------

    def test_historico_nao_pode_ser_alterado_nem_apagado(self):
        self.assert_recusado("UPDATE movimentacoes SET quantidade = 999")
        self.assert_recusado("DELETE FROM movimentacoes")
        self.assertEqual(self.contar_movimentacoes(), 2)

    # ---------- Itens e usuários nunca são apagados de verdade ----------

    def test_item_e_usuario_nao_sao_apagados(self):
        self.assert_recusado("DELETE FROM produtos")
        self.assert_recusado("DELETE FROM rolos_tecido")
        self.assert_recusado("DELETE FROM usuarios")

    def test_codigo_da_etiqueta_nao_muda(self):
        self.assert_recusado("UPDATE produtos SET codigo = 'PJ-NOVO' WHERE codigo = ?", (self.pijama,))
        self.assert_recusado("UPDATE rolos_tecido SET id = 77")
        with self.assertRaises(sqlite3.OperationalError):  # coluna calculada: nem dá para escrever
            banco.executar("UPDATE rolos_tecido SET codigo = 'RL-000077'")

    def test_login_nao_muda(self):
        self.assert_recusado("UPDATE usuarios SET login = 'outro' WHERE login = 'admin'")

    def test_item_excluido_nao_volta(self):
        banco.definir_item_ativo(self.pijama, False)
        banco.excluir_item(self.pijama)
        self.assert_recusado("UPDATE produtos SET excluido = 0, ativo = 1")
        self.assertIsNone(banco.buscar_item(self.pijama))

    # ---------- Valores fora do permitido ----------

    def test_valores_invalidos_sao_recusados(self):
        for sql in [
            "UPDATE produtos SET ativo = 7",
            "UPDATE produtos SET excluido = 1",                 # excluído precisa estar desativado
            "UPDATE produtos SET modelo = '   '",
            "UPDATE rolos_tecido SET limite_baixo = -1",
            "UPDATE usuarios SET master = 2",
        ]:
            with self.subTest(sql=sql):
                self.assert_recusado(sql)

    def test_codigo_de_pijama_invalido(self):
        for codigo in ["RL-000099", "pj-minusculo", "PJ COM ESPACO", "PJ-ÇÃO", "", "X" * 31]:
            with self.subTest(codigo=codigo):
                self.assert_recusado(
                    "INSERT INTO produtos (codigo, modelo, tamanho, cor) VALUES (?, 'X', 'Y', 'Z')", (codigo,))

    def test_movimentacao_com_valores_invalidos(self):
        sql = ("INSERT INTO movimentacoes (tipo_item, codigo_item, tipo, quantidade, data, motivo, usuario) "
               "VALUES ('produto', ?, ?, ?, ?, ?, 'admin')")
        for tipo, quantidade, data, motivo in [
            ("entrada", 1, "2026-11-12 10:00:00", "inventado"),   # motivo que não existe
            ("entrada", 1, "12/11/2026", "producao"),             # data em outro formato
            ("entrada", 1.5, "2026-11-12 10:00:00", "producao"),  # meio pijama
            ("entrada", 0, "2026-11-12 10:00:00", "producao"),    # quantidade zero
            ("sumiu", 1, "2026-11-12 10:00:00", "producao"),      # tipo que não existe
        ]:
            with self.subTest(motivo=motivo, data=data, quantidade=quantidade, tipo=tipo):
                self.assert_recusado(sql, (self.pijama, tipo, quantidade, data, motivo))

    def test_so_um_master_e_ele_e_administrador(self):
        usuarios.criar_usuario("Dono", "dono", SENHA_PADRAO, "admin", master=True)
        self.assert_recusado("UPDATE usuarios SET master = 1 WHERE login = 'admin'")  # segundo master
        self.assert_recusado("UPDATE usuarios SET perfil = 'operador' WHERE login = 'dono'")
        self.assert_recusado("UPDATE usuarios SET ativo = 0 WHERE login = 'dono'")

    def test_codigo_do_rolo_e_calculado_pelo_banco(self):
        self.assertEqual(banco.cadastrar_rolo("Seda", "Branco", "5", ADMIN), "RL-000002")
        self.assertEqual(banco.consultar_um("SELECT codigo FROM rolos_tecido WHERE id = 2")["codigo"], "RL-000002")


class TestePijamaRepetidoComMensagem(TesteComBancoLimpo):
    """O Python avisa antes do banco, com uma mensagem que diz qual é o pijama que já existe."""

    def setUp(self):
        super().setUp()
        self.pijama = banco.cadastrar_produto("Coração", "M", "Azul Claro", "1", ADMIN)

    def test_cadastrar_de_novo_com_outro_codigo(self):
        for modelo, tamanho, cor in [("Coração", "M", "Azul Claro"), ("coracao", "m", " azul   claro ")]:
            with self.subTest(modelo=modelo, cor=cor):
                with self.assertRaises(banco.ErroEstoque) as contexto:
                    banco.cadastrar_produto(modelo, tamanho, cor, "1", ADMIN, codigo="PJ-OUTRO")
                self.assertIn(f"já está cadastrado: {self.pijama}", str(contexto.exception))
        self.assertEqual(len(banco.listar_produtos()), 1)

    def test_repetido_desativado_pede_para_reativar(self):
        banco.definir_item_ativo(self.pijama, False)
        with self.assertRaises(banco.ErroEstoque) as contexto:
            banco.cadastrar_produto("Coração", "M", "Azul Claro", "1", ADMIN, codigo="PJ-OUTRO")
        self.assertIn("Reative", str(contexto.exception))

    def test_editar_para_ficar_igual_a_outro(self):
        outro = banco.cadastrar_produto("Coração", "G", "Azul Claro", "1", ADMIN)
        with self.assertRaises(banco.ErroEstoque):
            banco.editar_produto(outro, "Coração", "M", "Azul Claro")
        self.assertEqual(banco.buscar_produto(outro)["tamanho"], "G")
        # Editar o próprio pijama sem mudar a combinação continua valendo
        banco.editar_produto(self.pijama, "Coração", "M", "Azul Claro", "9")

    def test_codigo_de_excluido_continua_reservado(self):
        banco.definir_item_ativo(self.pijama, False)
        banco.excluir_item(self.pijama)
        with self.assertRaises(banco.ErroEstoque) as contexto:
            banco.cadastrar_produto("Outro", "M", "Azul", "1", ADMIN, codigo=self.pijama)
        self.assertIn("pijama excluído", str(contexto.exception))


class TesteConferenciaDoBanco(TesteComCliente):

    def setUp(self):
        super().setUp()
        self.pijama = banco.cadastrar_produto("Floral", "M", "Azul", "10", ADMIN)

    def test_banco_novo_esta_certo(self):
        self.assertEqual(banco.verificar_integridade(), [])
        self.assertIn("Tudo certo", self.admin.get("/admin").get_data(as_text=True))

    def test_saldo_mexido_por_fora_aparece_na_conferencia(self):
        banco.executar("UPDATE produtos SET quantidade = 99")  # sem movimentação!
        problemas = banco.verificar_integridade()
        self.assertEqual(problemas, ["PJ-FLO-M-AZ: saldo 99 un., mas o histórico soma 10."])
        self.assertIn("saldo 99 un.", self.admin.get("/admin").get_data(as_text=True))

    def test_ligacao_quebrada_por_fora_aparece_na_conferencia(self):
        # Simula alguém que desligou as proteções e gravou direto no arquivo
        conexao = sqlite3.connect(banco.CAMINHO_BANCO)
        conexao.execute("DROP TRIGGER mov_item_precisa_existir")
        conexao.execute(
            "INSERT INTO movimentacoes (tipo_item, codigo_item, tipo, quantidade, data, motivo, usuario) "
            "VALUES ('produto', 'PJ-FANTASMA', 'entrada', 1, '2026-11-12 10:00:00', 'ajuste', 'fantasma')")
        conexao.commit()
        conexao.close()
        problemas = " | ".join(banco.verificar_integridade())
        self.assertIn("usuário que não existe", problemas)
        self.assertIn("PJ-FANTASMA, que não existe", problemas)


if __name__ == "__main__":
    unittest.main()
