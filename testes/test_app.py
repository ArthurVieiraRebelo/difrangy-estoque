"""Testes das rotas (app.py), usando o "cliente de teste" do Flask.

O cliente de teste faz pedidos ao sistema como se fosse um navegador,
mas sem precisar ligar o servidor.
"""

import unittest

import banco
from app import app
from testes import TesteComBancoLimpo


class TesteApi(TesteComBancoLimpo):

    def setUp(self):
        super().setUp()
        self.cliente = app.test_client()
        self.pijama = banco.cadastrar_produto("Floral", "M", "Azul", "5")

    def movimentar(self, **dados):
        return self.cliente.post("/api/movimentar", json=dados)

    def test_movimentar_devolve_saldo_novo(self):
        resposta = self.movimentar(codigo=self.pijama, tipo="saida", quantidade=2, motivo="venda")
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.get_json()["item"]["saldo"], 3)

    def test_erro_de_regra_devolve_400_com_mensagem(self):
        resposta = self.movimentar(codigo=self.pijama, tipo="saida", quantidade=99, motivo="venda")
        self.assertEqual(resposta.status_code, 400)
        self.assertIn("insuficiente", resposta.get_json()["erro"])

    def test_pedido_sem_json_nao_quebra(self):
        resposta = self.cliente.post("/api/movimentar", data="lixo")
        self.assertEqual(resposta.status_code, 400)

    def test_item_inexistente_devolve_404(self):
        self.assertEqual(self.cliente.get("/api/item/NAOEXISTE").status_code, 404)

    def test_painel_traz_todas_as_partes(self):
        dados = self.cliente.get("/api/painel").get_json()
        for chave in ["resumo", "produtos", "rolos", "movimentacoes", "limites"]:
            self.assertIn(chave, dados)


class TestePaginas(TesteComBancoLimpo):

    def setUp(self):
        super().setUp()
        self.cliente = app.test_client()

    def test_todas_as_paginas_abrem(self):
        banco.cadastrar_produto("Floral", "M", "Azul", "5")
        for endereco in ["/", "/bipar", "/produtos", "/rolos", "/movimentacoes",
                         "/relatorios", "/etiqueta/PJ-FLO-M-AZ"]:
            with self.subTest(endereco=endereco):
                self.assertEqual(self.cliente.get(endereco).status_code, 200)

    def test_cadastro_pelo_formulario_redireciona_para_etiqueta(self):
        resposta = self.cliente.post("/rolos", data={"tipo_tecido": "Malha", "cor": "Azul", "metragem": "50"})
        self.assertEqual(resposta.status_code, 302)
        self.assertTrue(resposta.location.endswith("/etiqueta/RL-000001"))

    def test_numeros_e_datas_no_formato_brasileiro(self):
        banco.cadastrar_rolo("Malha", "Azul", "1234.5")
        self.assertIn("1.234,50", self.cliente.get("/rolos").get_data(as_text=True))
        self.assertRegex(self.cliente.get("/movimentacoes").get_data(as_text=True),
                         r"\d{2}/\d{2}/\d{4} \d{2}:\d{2}")

    def test_imagem_do_codigo_de_barras(self):
        resposta = self.cliente.get("/codigo-barras/PJ-FLO-M-AZ.png")
        self.assertEqual(resposta.mimetype, "image/png")


if __name__ == "__main__":
    unittest.main()
