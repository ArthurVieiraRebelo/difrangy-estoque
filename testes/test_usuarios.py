"""Testes do cadastro de usuários e da verificação de senha (usuarios.py)."""

import unittest

import banco
import usuarios
from testes import TesteComBancoLimpo


class TesteUsuarios(TesteComBancoLimpo):

    def setUp(self):
        super().setUp()
        usuarios.criar_usuario("Ana", "ana", "senha123", "admin")
        self.ana = usuarios.autenticar("ana", "senha123")

    def test_senha_nao_e_guardada_em_texto(self):
        linha = banco.consultar_um("SELECT senha_hash FROM usuarios WHERE login = 'ana'")
        self.assertNotIn("senha123", linha["senha_hash"])

    def test_login_certo_e_errado(self):
        self.assertIsNotNone(self.ana)
        self.assertIsNone(usuarios.autenticar("ana", "errada"))
        self.assertIsNone(usuarios.autenticar("ninguem", "senha123"))

    def test_login_ignora_maiusculas_e_espacos(self):
        self.assertIsNotNone(usuarios.autenticar("  ANA ", "senha123"))

    def test_login_duplicado_e_recusado(self):
        with self.assertRaises(usuarios.ErroUsuario):
            usuarios.criar_usuario("Outra Ana", "ana", "senha123", "operador")

    def test_validacoes_do_cadastro(self):
        casos = [
            ("", "bia", "senha123", "operador"),        # sem nome
            ("Bia", "b", "senha123", "operador"),       # login curto
            ("Bia", "bia silva", "senha123", "operador"),  # espaço no login
            ("Bia", "bia", "123", "operador"),          # senha curta
            ("Bia", "bia", "senha123", "chefe"),        # perfil inexistente
        ]
        for caso in casos:
            with self.subTest(caso=caso), self.assertRaises(usuarios.ErroUsuario):
                usuarios.criar_usuario(*caso)

    def test_usuario_desativado_nao_entra(self):
        usuarios.criar_usuario("Bia", "bia", "senha123", "operador")
        bia = usuarios.autenticar("bia", "senha123")
        usuarios.alterar_usuario(bia["id"], "operador", ativo=False, quem_alterou=self.ana)
        self.assertIsNone(usuarios.autenticar("bia", "senha123"))

    def test_trocar_propria_senha(self):
        usuarios.trocar_propria_senha(self.ana, "senha123", "novaSenha1", "novaSenha1")
        self.assertIsNone(usuarios.autenticar("ana", "senha123"))
        self.assertIsNotNone(usuarios.autenticar("ana", "novaSenha1"))

    def test_trocar_senha_exige_a_atual_e_confirmacao(self):
        with self.assertRaises(usuarios.ErroUsuario):
            usuarios.trocar_propria_senha(self.ana, "errada", "novaSenha1", "novaSenha1")
        with self.assertRaises(usuarios.ErroUsuario):
            usuarios.trocar_propria_senha(self.ana, "senha123", "novaSenha1", "diferente")

    def test_ultimo_admin_nao_pode_ser_rebaixado_por_ninguem(self):
        # Mesmo pedido por OUTRA pessoa (ex: um operador, se algum dia uma tela
        # deixar), o último administrador ativo não pode perder o acesso.
        usuarios.criar_usuario("Bia", "bia", "senha123", "operador")
        bia = usuarios.autenticar("bia", "senha123")
        for perfil, ativo in [("operador", True), ("admin", False)]:
            with self.subTest(perfil=perfil, ativo=ativo), self.assertRaises(usuarios.ErroUsuario):
                usuarios.alterar_usuario(self.ana["id"], perfil, ativo=ativo, quem_alterou=bia)
        self.assertIsNotNone(usuarios.autenticar("ana", "senha123"))

    def test_nao_pode_ficar_sem_administrador(self):
        # Ana é a única admin: não pode virar operadora nem ser desativada
        with self.assertRaises(usuarios.ErroUsuario):
            usuarios.alterar_usuario(self.ana["id"], "operador", ativo=True, quem_alterou=self.ana)

        usuarios.criar_usuario("Caio", "caio", "senha123", "admin")
        caio = usuarios.autenticar("caio", "senha123")
        # Nem com outro admin existindo alguém pode tirar o PRÓPRIO acesso
        with self.assertRaises(usuarios.ErroUsuario):
            usuarios.alterar_usuario(self.ana["id"], "admin", ativo=False, quem_alterou=self.ana)
        # Mas o Caio pode desativar a Ana, porque ele continua admin
        usuarios.alterar_usuario(self.ana["id"], "admin", ativo=False, quem_alterou=caio)
        self.assertIsNone(usuarios.autenticar("ana", "senha123"))


if __name__ == "__main__":
    unittest.main()
