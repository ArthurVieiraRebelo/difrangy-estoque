"""Testes das telas do master (configurações), do QR code e da exclusão de itens."""

import unittest

import banco
import configuracoes
import usuarios
from testes import ADMIN, SENHA_PADRAO, TesteComBancoLimpo, TesteComCliente


class TestePrimeiroAcessoViraMaster(TesteComBancoLimpo):

    criar_usuarios_de_mentira = False  # o primeiro acesso só aparece com o banco sem usuários

    def test_quem_faz_o_primeiro_acesso_e_o_master(self):
        from app import app
        cliente = app.test_client()
        cliente.post("/primeiro-acesso", data={
            "nome": "Dono", "login": "dono", "senha": SENHA_PADRAO, "confirmacao": SENHA_PADRAO,
        })
        self.assertTrue(usuarios.eh_master(usuarios.autenticar("dono", SENHA_PADRAO)))


class TesteConfiguracoes(TesteComCliente):

    def setUp(self):
        super().setUp()
        # Caio é administrador, mas NÃO é o master
        usuarios.criar_usuario("Caio Admin", "caio", SENHA_PADRAO, "admin")
        self.caio = self.cliente_logado("caio")
        self.pijama = banco.cadastrar_produto("Floral", "M", "Azul", "5", ADMIN)

    def desligar(self, *tipos):
        """O master salva as configurações deixando ligados só os tipos que NÃO estão em 'tipos'."""
        dados = {tipo: "1" for tipo in configuracoes.TIPOS_ETIQUETA if tipo not in tipos}
        return self.admin.post("/admin/configuracoes", data=dados)

    def test_so_o_master_ve_e_altera_as_configuracoes(self):
        self.assertIn("Configurações do sistema", self.admin.get("/admin").get_data(as_text=True))
        self.assertNotIn("Configurações do sistema", self.caio.get("/admin").get_data(as_text=True))
        self.assertEqual(self.caio.post("/admin/configuracoes", data={}).status_code, 403)
        self.assertEqual(self.operador.post("/admin/configuracoes", data={}).status_code, 403)
        self.assertTrue(configuracoes.etiqueta_liberada("qr"))  # nada mudou

    def test_desligar_qr_esconde_o_botao_e_bloqueia_o_endereco(self):
        self.desligar("qr")
        html = self.operador.get("/produtos").get_data(as_text=True)
        self.assertNotIn("Gerar QR code", html)
        self.assertIn("Gerar código de barras", html)

        # Mesmo digitando o endereço direto, o servidor recusa
        resposta = self.operador.get(f"/etiquetas?tipo=qr&codigo={self.pijama}")
        self.assertEqual(resposta.status_code, 302)
        self.assertEqual(self.operador.get(f"/etiquetas?tipo=barras&codigo={self.pijama}").status_code, 200)

    def test_desligar_os_dois_tipos(self):
        self.desligar("qr", "barras")
        html = self.operador.get("/rolos").get_data(as_text=True)
        self.assertNotIn("botao-gerar", html)
        self.assertIn("desligada nas configurações", html)

    def test_religar(self):
        self.desligar("qr")
        self.desligar()  # liga tudo de novo
        self.assertTrue(configuracoes.etiqueta_liberada("qr"))

    def test_master_aparece_protegido_na_lista_de_usuarios(self):
        html = self.caio.get("/admin").get_data(as_text=True)
        self.assertIn("Dono do sistema", html)
        ana = usuarios.autenticar("ana", SENHA_PADRAO)
        resposta = self.caio.post(f"/admin/usuarios/{ana['id']}/senha", data={"nova_senha": "tomei123"})
        self.assertEqual(resposta.status_code, 302)
        self.assertIsNotNone(usuarios.autenticar("ana", SENHA_PADRAO))  # senha não mudou


class TesteQrCode(TesteComCliente):

    def setUp(self):
        super().setUp()
        self.pijama = banco.cadastrar_produto("Floral", "M", "Azul", "5", ADMIN)

    def test_imagem_do_qrcode(self):
        resposta = self.operador.get(f"/qrcode/{self.pijama}.png")
        self.assertEqual(resposta.mimetype, "image/png")
        self.assertTrue(resposta.data.startswith(b"\x89PNG"))
        self.assertEqual(self.operador.get("/qrcode/c%C3%B3digo inválido.png").status_code, 404)

    def test_pagina_de_etiquetas_qr(self):
        html = self.operador.get(f"/etiquetas?tipo=qr&codigo={self.pijama}&copias=2").get_data(as_text=True)
        self.assertEqual(html.count(f"/qrcode/{self.pijama}.png"), 2)
        self.assertNotIn("/codigo-barras/", html)
        # O "Atualizar cópias" precisa manter o tipo escolhido
        self.assertIn('name="tipo" value="qr"', html)

    def test_tipo_inexistente_e_recusado(self):
        self.assertEqual(self.operador.get(f"/etiquetas?tipo=xyz&codigo={self.pijama}").status_code, 302)


class TesteExclusaoPelasTelas(TesteComCliente):

    def setUp(self):
        super().setUp()
        self.pijama = banco.cadastrar_produto("Floral", "M", "Azul", "5", ADMIN)

    def test_botao_excluir_so_aparece_com_item_desativado(self):
        endereco = f"/itens/{self.pijama}/editar"
        self.assertNotIn("Excluir definitivamente", self.admin.get(endereco).get_data(as_text=True))
        banco.definir_item_ativo(self.pijama, False)
        self.assertIn("Excluir definitivamente", self.admin.get(endereco).get_data(as_text=True))

    def test_admin_exclui_item_desativado(self):
        banco.definir_item_ativo(self.pijama, False)
        resposta = self.admin.post(f"/itens/{self.pijama}/excluir")
        self.assertTrue(resposta.location.endswith("/produtos"))
        self.assertIsNone(banco.buscar_produto(self.pijama))
        html = self.admin.get(f"/movimentacoes?codigo={self.pijama}").get_data(as_text=True)
        self.assertIn("Pijama Floral · M · Azul (excluído)", html)

    def test_excluir_item_ativo_e_recusado(self):
        self.admin.post(f"/itens/{self.pijama}/excluir")
        self.assertIsNotNone(banco.buscar_produto(self.pijama))

    def test_operador_nao_exclui(self):
        banco.definir_item_ativo(self.pijama, False)
        self.assertEqual(self.operador.post(f"/itens/{self.pijama}/excluir").status_code, 403)
        self.assertIsNotNone(banco.buscar_produto(self.pijama))


if __name__ == "__main__":
    unittest.main()
