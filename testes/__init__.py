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
# O app.py cria as tabelas assim que é importado, então já apontamos
# para um arquivo temporário, para ele não criar o estoque.db de verdade.
os.environ["ESTOQUE_DB"] = os.path.join(tempfile.mkdtemp(), "importacao.db")

import banco  # noqa: E402  (precisa vir depois da linha acima)


class TesteComBancoLimpo(unittest.TestCase):
    """Classe base: antes de CADA teste, cria um banco vazio só para ele."""

    def setUp(self):
        self.pasta_temporaria = tempfile.TemporaryDirectory()
        banco.CAMINHO_BANCO = Path(self.pasta_temporaria.name) / "teste.db"
        banco.criar_tabelas()

    def tearDown(self):
        self.pasta_temporaria.cleanup()  # apaga a pasta e o banco do teste

    def contar_movimentacoes(self):
        return banco.consultar_um("SELECT COUNT(*) AS total FROM movimentacoes")["total"]
