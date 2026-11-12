"""Testes da checagem "a porta já está em uso?" que roda antes de o sistema subir."""

import socket
import unittest

import testes  # noqa: F401  (aponta o banco para um lugar temporário antes do app)
from app import porta_esta_livre


def porta_livre_qualquer():
    """Pede ao sistema operacional uma porta que ninguém está usando."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class TestePorta(unittest.TestCase):

    def test_porta_com_programa_escutando_esta_ocupada(self):
        with socket.socket() as servidor:
            servidor.bind(("0.0.0.0", 0))
            servidor.listen()
            self.assertFalse(porta_esta_livre(servidor.getsockname()[1]))

    def test_porta_sem_ninguem_esta_livre(self):
        self.assertTrue(porta_esta_livre(porta_livre_qualquer()))

    def test_porta_logo_depois_de_fechar_o_sistema_esta_livre(self):
        # Simula: o navegador estava conectado e o sistema foi fechado (Ctrl+C).
        # Quem fecha primeiro fica com a conexão em TIME_WAIT por um tempo.
        servidor = socket.socket()
        # O Waitress liga SO_REUSEADDR na porta dele (fora do Windows); fazemos igual
        servidor.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        servidor.bind(("0.0.0.0", 0))
        servidor.listen()
        porta = servidor.getsockname()[1]
        navegador = socket.create_connection(("127.0.0.1", porta))
        conexao, _ = servidor.accept()
        conexao.close()   # o servidor fecha a conexão primeiro...
        servidor.close()  # ...e para de escutar
        navegador.close()

        self.assertTrue(porta_esta_livre(porta))


if __name__ == "__main__":
    unittest.main()
