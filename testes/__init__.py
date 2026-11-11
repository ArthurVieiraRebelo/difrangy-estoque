"""
Testes automatizados do sistema.

Rodar todos (dentro da pasta Difrangy):
    .venv/bin/python -m unittest -v

Os testes NUNCA usam o estoque real (estoque.db): cada teste cria um banco
novo numa pasta temporária, que é apagada no final.
"""

import os
import tempfile
import unittest
from pathlib import Path

# Isto roda ANTES de qualquer teste importar o banco.py ou o app.py.
# O app.py cria as tabelas e a chave secreta assim que é importado, então
# apontamos tudo para lugares temporários, longe dos arquivos de verdade.
_PASTA_IMPORTACAO = tempfile.mkdtemp()
os.environ["ESTOQUE_DB"] = os.path.join(_PASTA_IMPORTACAO, "importacao.db")
os.environ["ESTOQUE_BACKUPS"] = os.path.join(_PASTA_IMPORTACAO, "backups")
os.environ["CHAVE_SECRETA"] = "chave-so-para-testes"

import backup    # noqa: E402  (precisa vir depois das linhas acima)
import banco     # noqa: E402
import usuarios  # noqa: E402

# Usuários "de mentira" para as funções do banco.py, que só olham login e perfil
ADMIN = {"login": "admin", "perfil": "admin"}
OPERADOR = {"login": "operador", "perfil": "operador"}

SENHA_PADRAO = "senha123"


class TesteComBancoLimpo(unittest.TestCase):
    """Classe base: antes de CADA teste, cria um banco vazio só para ele."""

    def setUp(self):
        self.pasta_temporaria = tempfile.TemporaryDirectory()
        pasta = Path(self.pasta_temporaria.name)
        banco.CAMINHO_BANCO = pasta / "teste.db"
        backup.PASTA_BACKUPS = pasta / "backups"
        banco.criar_tabelas()

    def tearDown(self):
        self.pasta_temporaria.cleanup()  # apaga a pasta e o banco do teste

    def contar_movimentacoes(self):
        return banco.consultar_um("SELECT COUNT(*) AS total FROM movimentacoes")["total"]


class TesteComCliente(TesteComBancoLimpo):
    """Classe base para testar as páginas: já cria um admin e um operador
    e oferece um "navegador de teste" (cliente) para cada um."""

    def setUp(self):
        super().setUp()
        from app import app  # importado aqui para usar o banco temporário
        self.app = app
        usuarios.criar_usuario("Ana Admin", "ana", SENHA_PADRAO, "admin")
        usuarios.criar_usuario("Otto Operador", "otto", SENHA_PADRAO, "operador")
        self.admin = self.cliente_logado("ana")
        self.operador = self.cliente_logado("otto")

    def cliente_logado(self, login):
        """Cria um "navegador" de teste e faz login nele."""
        cliente = self.app.test_client()
        resposta = cliente.post("/login", data={"login": login, "senha": SENHA_PADRAO})
        self.assertEqual(resposta.status_code, 302, "o login de teste deveria funcionar")
        return cliente
