"""Testes do código digitado "de qualquer jeito" e das sugestões da tela Bipar."""

import unittest

import banco
from testes import ADMIN, TesteComBancoLimpo, TesteComCliente


class TesteResolverCodigo(TesteComBancoLimpo):

    def setUp(self):
        super().setUp()
        self.pijama = banco.cadastrar_produto("Floral", "M", "Azul", "10", ADMIN)  # PJ-FLO-M-AZ
        self.rolo = banco.cadastrar_rolo("Malha", "Azul", "50", ADMIN)              # RL-000001

    def test_formas_diferentes_de_digitar_o_mesmo_codigo(self):
        for digitado in ["PJ-FLO-M-AZ", "pj-flo-m-az", "pjflomaz", "PJFLOMAZ", " pj flo m az ",
                         "pj.flo.m.az", "pj/flo/m/az", "Pj_Flo_M_Az"]:
            with self.subTest(digitado=digitado):
                self.assertEqual(banco.resolver_codigo_digitado(digitado), "PJ-FLO-M-AZ")

    def test_rolo_so_pelo_numero(self):
        for digitado in ["rl1", "RL 1", "rl-1", "rl000001", "RL-000001"]:
            with self.subTest(digitado=digitado):
                self.assertEqual(banco.resolver_codigo_digitado(digitado), "RL-000001")

    def test_codigo_que_nao_existe(self):
        for digitado in ["pjxyz", "rl99", "", "   ", "-", "a" * 40]:
            with self.subTest(digitado=digitado):
                self.assertIsNone(banco.resolver_codigo_digitado(digitado))

    def test_digitado_que_combina_com_dois_codigos(self):
        # Dois códigos manuais que só diferem na posição do hífen
        banco.cadastrar_produto("A", "M", "Azul", "0", ADMIN, codigo="PJ-AB-CD")
        banco.cadastrar_produto("B", "M", "Azul", "0", ADMIN, codigo="PJ-ABC-D")
        with self.assertRaises(banco.ErroEstoque):
            banco.resolver_codigo_digitado("pjabcd")
        # Com os hífens, não há dúvida
        self.assertEqual(banco.resolver_codigo_digitado("pj-ab-cd"), "PJ-AB-CD")

    def test_movimentacao_com_codigo_digitado_grava_o_codigo_oficial(self):
        item = banco.registrar_movimentacao("pjflomaz", "saida", "1", "venda", ADMIN)
        self.assertEqual(item["saldo"], 9)
        self.assertEqual(banco.listar_movimentacoes(limite=1)[0]["codigo_item"], "PJ-FLO-M-AZ")

    def test_corte_de_rolo_pelo_numero(self):
        item = banco.registrar_movimentacao("rl1", "saida", "2,5", "corte", ADMIN)
        self.assertEqual(item["saldo"], 47.5)


class TesteSugestoes(TesteComBancoLimpo):

    def setUp(self):
        super().setUp()
        for modelo, tamanho, cor in [("Floral", "P", "Azul"), ("Floral", "M", "Azul"),
                                     ("Floral", "M", "Rosa"), ("Coração", "G", "Verde")]:
            banco.cadastrar_produto(modelo, tamanho, cor, "1", ADMIN)
        banco.cadastrar_rolo("Malha", "Azul", "50", ADMIN)
        banco.cadastrar_rolo("Algodão", "Branco", "30", ADMIN)

    def codigos(self, texto):
        return [s["codigo"] for s in banco.sugerir_itens(texto)]

    def test_pelo_inicio_do_codigo_sem_hifen(self):
        self.assertEqual(self.codigos("pjflom"), ["PJ-FLO-M-AZ", "PJ-FLO-M-RO"])

    def test_por_palavras_da_descricao(self):
        self.assertEqual(self.codigos("floral azul"), ["PJ-FLO-M-AZ", "PJ-FLO-P-AZ"])
        self.assertEqual(self.codigos("malha"), ["RL-000001"])

    def test_ignora_acentos(self):
        self.assertEqual(self.codigos("coracao"), ["PJ-COR-G-VE"])
        self.assertEqual(self.codigos("algodão"), ["RL-000002"])

    def test_codigo_exato_aparece_primeiro(self):
        self.assertEqual(self.codigos("rl2")[0], "RL-000002")
        # "PJ-A-BC" vem antes de "PJ-AB" em ordem alfabética, e os dois começam
        # com "PJAB". Mesmo assim, quem digitou "pjab" quer o PJ-AB: ele vem primeiro.
        banco.cadastrar_produto("X", "M", "Azul", "0", ADMIN, codigo="PJ-A-BC")
        banco.cadastrar_produto("Y", "M", "Azul", "0", ADMIN, codigo="PJ-AB")
        self.assertEqual(self.codigos("pjab"), ["PJ-AB", "PJ-A-BC"])

    def test_nao_sugere_item_desativado(self):
        banco.definir_item_ativo("PJ-FLO-M-RO", False)
        self.assertNotIn("PJ-FLO-M-RO", self.codigos("floral"))

    def test_limite_de_sugestoes_e_texto_vazio(self):
        self.assertLessEqual(len(banco.sugerir_itens("a", limite=3)), 3)
        self.assertEqual(banco.sugerir_itens("   "), [])

    def test_sugestao_traz_o_que_a_tela_mostra(self):
        sugestao = banco.sugerir_itens("rl1")[0]
        self.assertEqual(set(sugestao), {"codigo", "descricao", "saldo", "unidade", "tipo_item"})


class TesteApiComCodigoDigitado(TesteComCliente):

    def setUp(self):
        super().setUp()
        self.pijama = banco.cadastrar_produto("Floral", "M", "Azul", "10", ADMIN)

    def test_api_item_aceita_codigo_sem_hifen_e_com_barras(self):
        for digitado in ["pjflomaz", "pj/flo/m/az", "PJ FLO M AZ"]:
            with self.subTest(digitado=digitado):
                resposta = self.operador.get(f"/api/item/{digitado}")
                self.assertEqual(resposta.status_code, 200)
                self.assertEqual(resposta.get_json()["item"]["codigo"], "PJ-FLO-M-AZ")

    def test_api_movimentar_com_codigo_minusculo(self):
        resposta = self.operador.post("/api/movimentar", json={
            "codigo": "pjflomaz", "tipo": "saida", "quantidade": 1, "motivo": "venda",
        })
        self.assertEqual(resposta.get_json()["item"]["saldo"], 9)

    def test_api_sugestoes(self):
        dados = self.operador.get("/api/sugestoes?q=floral").get_json()
        self.assertTrue(dados["ok"])
        self.assertEqual(dados["sugestoes"][0]["codigo"], "PJ-FLO-M-AZ")

    def test_api_sugestoes_exige_login(self):
        self.assertEqual(self.app.test_client().get("/api/sugestoes?q=floral").status_code, 401)

    def test_codigo_ambiguo_responde_com_mensagem(self):
        banco.cadastrar_produto("A", "M", "Azul", "0", ADMIN, codigo="PJ-AB-CD")
        banco.cadastrar_produto("B", "M", "Azul", "0", ADMIN, codigo="PJ-ABC-D")
        resposta = self.operador.get("/api/item/pjabcd")
        self.assertEqual(resposta.status_code, 400)
        self.assertIn("mais de um código", resposta.get_json()["erro"])

    def test_filtro_do_historico_aceita_codigo_sem_hifen(self):
        html = self.operador.get("/movimentacoes?codigo=pjflomaz").get_data(as_text=True)
        self.assertIn("Histórico de PJ-FLO-M-AZ", html)


if __name__ == "__main__":
    unittest.main()
