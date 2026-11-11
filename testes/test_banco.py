"""Testes das regras de negócio (banco.py)."""

import unittest

import banco
from testes import ADMIN, OPERADOR, TesteComBancoLimpo


class TesteCodigos(unittest.TestCase):
    """Funções que não usam o banco: não precisam da classe base."""

    def test_gera_codigo_do_pijama_pelas_siglas(self):
        self.assertEqual(banco.gerar_codigo_produto("Floral", "M", "Azul"), "PJ-FLO-M-AZ")

    def test_codigo_tira_acentos(self):
        self.assertEqual(banco.gerar_codigo_produto("Coração", "gg", "Rosa"), "PJ-COR-GG-RO")

    def test_limpar_codigo_padroniza_maiusculo_e_sem_espacos(self):
        self.assertEqual(banco.limpar_codigo("  pj-flo-m-az "), "PJ-FLO-M-AZ")

    def test_codigo_com_simbolo_e_recusado(self):
        with self.assertRaises(banco.ErroEstoque):
            banco.limpar_codigo("PJ FLO")

    def test_codigo_muito_longo_e_recusado(self):
        with self.assertRaises(banco.ErroEstoque):
            banco.limpar_codigo("A" * 31)


class TesteQuantidades(unittest.TestCase):

    def test_pijama_aceita_inteiro(self):
        self.assertEqual(banco.converter_quantidade("3", "produto"), 3)

    def test_pijama_recusa_fracao(self):
        with self.assertRaises(banco.ErroEstoque):
            banco.converter_quantidade("1.5", "produto")

    def test_rolo_aceita_virgula(self):
        self.assertEqual(banco.converter_quantidade("12,5", "rolo"), 12.5)

    def test_zero_negativo_e_texto_sao_recusados(self):
        for valor in ["0", "-2", "abc", "", "inf", "nan"]:
            with self.subTest(valor=valor), self.assertRaises(banco.ErroEstoque):
                banco.converter_quantidade(valor, "rolo")

    def test_quantidade_absurda_e_recusada(self):
        with self.assertRaises(banco.ErroEstoque):
            banco.converter_quantidade("1e20", "produto")


class TesteCadastro(TesteComBancoLimpo):

    def test_cadastro_com_quantidade_grava_movimentacao_de_entrada(self):
        codigo = banco.cadastrar_produto("Floral", "M", "Azul", "10", ADMIN)

        self.assertEqual(codigo, "PJ-FLO-M-AZ")
        self.assertEqual(banco.buscar_produto(codigo)["quantidade"], 10)
        movimentacao = banco.listar_movimentacoes(codigo=codigo)[0]
        self.assertEqual(movimentacao["tipo"], "entrada")
        self.assertEqual(movimentacao["quantidade"], 10)
        self.assertEqual(movimentacao["motivo"], "estoque_inicial")

    def test_cadastro_com_zero_nao_grava_movimentacao(self):
        banco.cadastrar_produto("Floral", "M", "Azul", "0", ADMIN)
        self.assertEqual(self.contar_movimentacoes(), 0)

    def test_codigo_duplicado_e_recusado(self):
        banco.cadastrar_produto("Floral", "M", "Azul", "0", ADMIN)
        with self.assertRaises(banco.ErroEstoque):
            banco.cadastrar_produto("Floral", "M", "Azul", "0", ADMIN)

    def test_pijama_nao_pode_usar_prefixo_de_rolo(self):
        with self.assertRaises(banco.ErroEstoque):
            banco.cadastrar_produto("Floral", "M", "Azul", "0", ADMIN, codigo="RL-000001")

    def test_rolo_recebe_codigo_sequencial(self):
        self.assertEqual(banco.cadastrar_rolo("Malha", "Azul", "25,5", ADMIN), "RL-000001")
        self.assertEqual(banco.cadastrar_rolo("Malha", "Rosa", "10", ADMIN), "RL-000002")
        self.assertEqual(banco.buscar_rolo("RL-000001")["metragem_atual"], 25.5)


class TesteMovimentacao(TesteComBancoLimpo):

    def setUp(self):
        super().setUp()  # cria o banco limpo (classe base)
        self.pijama = banco.cadastrar_produto("Floral", "M", "Azul", "10", ADMIN)
        self.rolo = banco.cadastrar_rolo("Malha", "Azul", "25.5", ADMIN)

    def test_saida_desconta_e_registra_movimentacao(self):
        antes = self.contar_movimentacoes()
        item = banco.registrar_movimentacao(self.pijama, "saida", "2", "venda", ADMIN)

        self.assertEqual(item["saldo"], 8)
        self.assertEqual(self.contar_movimentacoes(), antes + 1)

    def test_entrada_soma(self):
        item = banco.registrar_movimentacao(self.pijama, "entrada", "5", "producao", ADMIN)
        self.assertEqual(item["saldo"], 15)

    def test_saida_maior_que_saldo_nao_altera_nada(self):
        antes = self.contar_movimentacoes()
        with self.assertRaises(banco.ErroEstoque):
            banco.registrar_movimentacao(self.pijama, "saida", "11", "venda", ADMIN)

        # A regra mais importante: nem o saldo nem o histórico mudaram
        self.assertEqual(banco.buscar_produto(self.pijama)["quantidade"], 10)
        self.assertEqual(self.contar_movimentacoes(), antes)

    def test_pode_zerar_o_estoque_exatamente(self):
        item = banco.registrar_movimentacao(self.pijama, "saida", "10", "venda", ADMIN)
        self.assertEqual(item["saldo"], 0)

    def test_cortes_decimais_zeram_o_rolo_sem_sobra(self):
        # No computador, 1 - 0.9 - 0.1 dá -0.00000000000000003 (e não 0).
        # Sem o ROUND do banco.py, o último corte seria recusado como "insuficiente".
        rolo = banco.cadastrar_rolo("Malha", "Rosa", "1", ADMIN)
        item = banco.registrar_movimentacao(rolo, "saida", "0,9", "corte", ADMIN)
        self.assertEqual(item["saldo"], 0.1)
        item = banco.registrar_movimentacao(rolo, "saida", "0,1", "corte", ADMIN)
        self.assertEqual(item["saldo"], 0)

    def test_motivo_de_pijama_em_rolo_e_recusado(self):
        with self.assertRaises(banco.ErroEstoque):
            banco.registrar_movimentacao(self.rolo, "saida", "1", "venda", ADMIN)

    def test_codigo_inexistente(self):
        with self.assertRaises(banco.ErroEstoque):
            banco.registrar_movimentacao("PJ-NAO-EXISTE", "saida", "1", "venda", ADMIN)

    def test_codigo_bipado_em_minusculo_funciona(self):
        item = banco.registrar_movimentacao(self.pijama.lower(), "saida", "1", "venda", ADMIN)
        self.assertEqual(item["saldo"], 9)


class TesteRelatorios(TesteComBancoLimpo):

    def test_resumo_e_relatorios(self):
        pijama = banco.cadastrar_produto("Floral", "M", "Azul", "3", ADMIN)  # 3 <= 5: estoque baixo
        rolo = banco.cadastrar_rolo("Malha", "Azul", "10", ADMIN)
        banco.registrar_movimentacao(pijama, "saida", "1", "venda", ADMIN)
        banco.registrar_movimentacao(rolo, "saida", "8", "corte", ADMIN)    # sobra 2 m: acabando

        resumo = banco.resumo()
        self.assertEqual(resumo["pijamas_unidades"], 2)
        self.assertEqual(resumo["rolos_metros"], 2)
        self.assertEqual(resumo["itens_baixos"], 2)

        self.assertEqual(banco.relatorio_consumo_tecido_por_mes()[0]["metros"], 8)
        self.assertEqual(banco.relatorio_pijamas_vendidos_por_mes()[0]["unidades"], 1)


class TestePermissoesEUsuario(TesteComBancoLimpo):

    def setUp(self):
        super().setUp()
        self.pijama = banco.cadastrar_produto("Floral", "M", "Azul", "10", ADMIN)

    def test_movimentacao_guarda_quem_fez(self):
        banco.registrar_movimentacao(self.pijama, "saida", "1", "venda", OPERADOR)
        self.assertEqual(banco.listar_movimentacoes(limite=1)[0]["usuario"], "operador")

    def test_operador_nao_pode_fazer_ajuste(self):
        with self.assertRaises(banco.ErroEstoque):
            banco.registrar_movimentacao(self.pijama, "saida", "1", "ajuste", OPERADOR)
        self.assertEqual(banco.buscar_produto(self.pijama)["quantidade"], 10)

    def test_admin_pode_fazer_ajuste(self):
        item = banco.registrar_movimentacao(self.pijama, "saida", "1", "ajuste", ADMIN)
        self.assertEqual(item["saldo"], 9)

    def test_lista_de_motivos_do_operador_nao_tem_ajuste(self):
        motivos = banco.motivos_permitidos_para("operador")
        self.assertNotIn("ajuste", motivos["produto"]["saida"])
        self.assertEqual(motivos["rolo"]["entrada"], [])
        self.assertIn("ajuste", banco.motivos_permitidos_para("admin")["produto"]["saida"])


class TesteEdicaoEDesativacao(TesteComBancoLimpo):

    def setUp(self):
        super().setUp()
        self.pijama = banco.cadastrar_produto("Floral", "M", "Azul", "10", ADMIN)

    def test_editar_muda_descricao_mas_nao_codigo_nem_saldo(self):
        banco.editar_produto(self.pijama, "Floral Clássico", "g", "Azul Claro")
        produto = banco.buscar_produto(self.pijama)
        self.assertEqual((produto["modelo"], produto["tamanho"], produto["cor"]),
                         ("Floral Clássico", "G", "Azul Claro"))
        self.assertEqual(produto["quantidade"], 10)

    def test_editar_com_campo_vazio_e_recusado(self):
        with self.assertRaises(banco.ErroEstoque):
            banco.editar_produto(self.pijama, "  ", "M", "Azul")

    def test_item_desativado_nao_aceita_bipe_e_some_do_painel(self):
        banco.definir_item_ativo(self.pijama, False)
        with self.assertRaises(banco.ErroEstoque):
            banco.registrar_movimentacao(self.pijama, "saida", "1", "venda", ADMIN)
        self.assertEqual(banco.listar_produtos(somente_ativos=True), [])
        self.assertEqual(banco.resumo()["pijamas_unidades"], 0)

    def test_reativar_volta_a_aceitar_bipe(self):
        banco.definir_item_ativo(self.pijama, False)
        banco.definir_item_ativo(self.pijama, True)
        item = banco.registrar_movimentacao(self.pijama, "saida", "1", "venda", ADMIN)
        self.assertEqual(item["saldo"], 9)


class TesteBancoAntigo(TesteComBancoLimpo):
    """Um banco criado pela primeira versão do sistema (sem as colunas novas)
    precisa continuar funcionando depois da atualização."""

    def test_colunas_novas_sao_adicionadas(self):
        conexao = banco.conectar()
        conexao.executescript("""
            DROP TABLE produtos; DROP TABLE movimentacoes;
            CREATE TABLE produtos (id INTEGER PRIMARY KEY, codigo TEXT UNIQUE, modelo TEXT,
                                   tamanho TEXT, cor TEXT, quantidade INTEGER);
            CREATE TABLE movimentacoes (id INTEGER PRIMARY KEY, tipo_item TEXT, codigo_item TEXT,
                                        tipo TEXT, quantidade REAL, data TEXT, motivo TEXT);
            INSERT INTO produtos VALUES (1, 'PJ-VEL-M-AZ', 'Velho', 'M', 'Azul', 4);
        """)
        conexao.close()

        banco.criar_tabelas()  # é o que acontece quando o sistema novo inicia

        produto = banco.buscar_produto("PJ-VEL-M-AZ")
        self.assertEqual(produto["ativo"], 1)  # itens antigos continuam ativos
        item = banco.registrar_movimentacao("PJ-VEL-M-AZ", "saida", "1", "venda", ADMIN)
        self.assertEqual(item["saldo"], 3)


if __name__ == "__main__":
    unittest.main()
