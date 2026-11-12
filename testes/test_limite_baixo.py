"""Testes do limite de estoque baixo definido para CADA pijama e CADA rolo."""

import sqlite3
import unittest

import banco
from testes import ADMIN, TesteComBancoLimpo, TesteComCliente


class TesteLimiteNoBanco(TesteComBancoLimpo):

    def test_pijama_novo_vem_com_o_limite_padrao(self):
        codigo = banco.cadastrar_produto("Floral", "M", "Azul", "10", ADMIN)
        self.assertEqual(banco.buscar_produto(codigo)["limite_baixo"], banco.LIMITE_PIJAMAS_BAIXO)

    def test_cadastro_com_limite_proprio(self):
        codigo = banco.cadastrar_produto("Floral", "M", "Azul", "10", ADMIN, limite_baixo="20")
        self.assertEqual(banco.buscar_produto(codigo)["limite_baixo"], 20)

    def test_cada_pijama_usa_o_seu_limite(self):
        # Os dois têm 10 unidades, mas só o que vende muito (limite 20) está baixo
        vende_muito = banco.cadastrar_produto("Floral", "M", "Azul", "10", ADMIN, limite_baixo="20")
        vende_pouco = banco.cadastrar_produto("Floral", "GG", "Azul", "10", ADMIN, limite_baixo="2")

        baixos = [p["codigo"] for p in banco.relatorio_pijamas_baixos()]
        self.assertEqual(baixos, [vende_muito])
        self.assertNotIn(vende_pouco, baixos)
        self.assertEqual(banco.resumo()["itens_baixos"], 1)

    def test_quantidade_igual_ao_limite_ja_e_baixo(self):
        # "Baixo com até 5" inclui o 5
        banco.cadastrar_produto("Floral", "M", "Azul", "5", ADMIN, limite_baixo="5")
        self.assertEqual(banco.resumo()["itens_baixos"], 1)

    def test_limite_zero_avisa_so_quando_acabar(self):
        codigo = banco.cadastrar_produto("Floral", "M", "Azul", "1", ADMIN, limite_baixo="0")
        self.assertEqual(banco.resumo()["itens_baixos"], 0)
        banco.registrar_movimentacao(codigo, "saida", "1", "venda", ADMIN)
        self.assertEqual(banco.resumo()["itens_baixos"], 1)

    def test_editar_o_limite(self):
        codigo = banco.cadastrar_produto("Floral", "M", "Azul", "10", ADMIN)
        banco.editar_produto(codigo, "Floral", "M", "Azul", "15")
        self.assertEqual(banco.buscar_produto(codigo)["limite_baixo"], 15)
        self.assertEqual(banco.resumo()["itens_baixos"], 1)

    def test_editar_sem_informar_o_limite_mantem_o_atual(self):
        codigo = banco.cadastrar_produto("Floral", "M", "Azul", "10", ADMIN, limite_baixo="12")
        banco.editar_produto(codigo, "Floral Novo", "M", "Azul")
        self.assertEqual(banco.buscar_produto(codigo)["limite_baixo"], 12)

    def test_limite_invalido(self):
        for digitado in ["-1", "2,5", "abc", "999999999"]:
            with self.subTest(digitado=digitado):
                with self.assertRaises(banco.ErroEstoque):
                    banco.cadastrar_produto("Floral", "M", "Azul", "0", ADMIN, limite_baixo=digitado)
        # Nada foi cadastrado com limite errado
        self.assertEqual(banco.listar_produtos(), [])

    def test_limite_invalido_na_edicao_nao_altera_nada(self):
        codigo = banco.cadastrar_produto("Floral", "M", "Azul", "10", ADMIN, limite_baixo="8")
        with self.assertRaises(banco.ErroEstoque):
            banco.editar_produto(codigo, "Outro", "M", "Azul", "-3")
        produto = banco.buscar_produto(codigo)
        self.assertEqual((produto["modelo"], produto["limite_baixo"]), ("Floral", 8))

    def test_o_proprio_banco_recusa_limite_negativo(self):
        banco.cadastrar_produto("Floral", "M", "Azul", "10", ADMIN)
        with self.assertRaises(sqlite3.IntegrityError):
            banco.executar("UPDATE produtos SET limite_baixo = -1")


class TesteLimiteDosRolos(TesteComBancoLimpo):

    def test_rolo_novo_vem_com_o_limite_padrao(self):
        codigo = banco.cadastrar_rolo("Malha", "Azul", "50", ADMIN)
        self.assertEqual(banco.buscar_rolo(codigo)["limite_baixo"], banco.LIMITE_METROS_BAIXO)

    def test_limite_em_metros_aceita_virgula(self):
        codigo = banco.cadastrar_rolo("Malha", "Azul", "50", ADMIN, limite_baixo="7,5")
        self.assertEqual(banco.buscar_rolo(codigo)["limite_baixo"], 7.5)

    def test_cada_rolo_usa_o_seu_limite(self):
        # Os dois têm 8 m, mas só o tecido mais usado (limite 10 m) está acabando
        mais_usado = banco.cadastrar_rolo("Malha", "Azul", "8", ADMIN, limite_baixo="10")
        menos_usado = banco.cadastrar_rolo("Seda", "Branco", "8", ADMIN, limite_baixo="2")

        acabando = [r["codigo"] for r in banco.relatorio_rolos_acabando()]
        self.assertEqual(acabando, [mais_usado])
        self.assertNotIn(menos_usado, acabando)
        self.assertEqual(banco.resumo()["itens_baixos"], 1)

    def test_metragem_igual_ao_limite_ja_esta_acabando(self):
        codigo = banco.cadastrar_rolo("Malha", "Azul", "10", ADMIN, limite_baixo="4,5")
        banco.registrar_movimentacao(codigo, "saida", "5,5", "corte", ADMIN)  # sobra 4,5 m
        self.assertEqual([r["codigo"] for r in banco.relatorio_rolos_acabando()], [codigo])

    def test_rolo_que_acabou_nao_conta_como_acabando(self):
        codigo = banco.cadastrar_rolo("Malha", "Azul", "2", ADMIN, limite_baixo="5")
        banco.registrar_movimentacao(codigo, "saida", "2", "corte", ADMIN)   # 0 m: acabou
        self.assertEqual(banco.relatorio_rolos_acabando(), [])
        self.assertEqual(banco.resumo()["itens_baixos"], 0)

    def test_editar_o_limite_do_rolo(self):
        codigo = banco.cadastrar_rolo("Malha", "Azul", "8", ADMIN)
        banco.editar_rolo(codigo, "Malha", "Azul", "12,25")
        self.assertEqual(banco.buscar_rolo(codigo)["limite_baixo"], 12.25)
        self.assertEqual(banco.resumo()["itens_baixos"], 1)

    def test_editar_rolo_sem_informar_o_limite_mantem_o_atual(self):
        codigo = banco.cadastrar_rolo("Malha", "Azul", "8", ADMIN, limite_baixo="6")
        banco.editar_rolo(codigo, "Malha Penteada", "Azul")
        self.assertEqual(banco.buscar_rolo(codigo)["limite_baixo"], 6)

    def test_limite_do_rolo_invalido(self):
        for digitado in ["-1", "abc", "inf", "nan", "999999999"]:
            with self.subTest(digitado=digitado):
                with self.assertRaises(banco.ErroEstoque):
                    banco.cadastrar_rolo("Malha", "Azul", "8", ADMIN, limite_baixo=digitado)
        self.assertEqual(banco.listar_rolos(), [])
        self.assertEqual(self.contar_movimentacoes(), 0)  # nem a entrada do rolo foi gravada

    def test_o_proprio_banco_recusa_limite_negativo_no_rolo(self):
        banco.cadastrar_rolo("Malha", "Azul", "8", ADMIN)
        with self.assertRaises(sqlite3.IntegrityError):
            banco.executar("UPDATE rolos_tecido SET limite_baixo = -0.5")


class TesteBancoDeVersaoAntiga(TesteComBancoLimpo):
    """O banco real da fábrica foi criado antes de existir o limite por pijama."""

    def test_pijamas_antigos_ganham_o_limite_padrao(self):
        # Recria a tabela como era nas versões antigas (sem limite_baixo)
        conexao = banco.conectar()
        conexao.executescript("""
            DROP TABLE produtos;
            CREATE TABLE produtos (
                id INTEGER PRIMARY KEY AUTOINCREMENT, codigo TEXT NOT NULL UNIQUE,
                modelo TEXT NOT NULL, tamanho TEXT NOT NULL, cor TEXT NOT NULL,
                quantidade INTEGER NOT NULL DEFAULT 0 CHECK (quantidade >= 0),
                ativo INTEGER NOT NULL DEFAULT 1
            );
            INSERT INTO produtos (codigo, modelo, tamanho, cor, quantidade)
            VALUES ('PJ-LIG-M-AZ', 'Liga', 'M', 'Azul', 3);
        """)
        conexao.close()

        banco.criar_tabelas()  # é o que acontece quando o sistema novo inicia

        self.assertEqual(banco.buscar_produto("PJ-LIG-M-AZ")["limite_baixo"], banco.LIMITE_PIJAMAS_BAIXO)
        self.assertEqual(banco.resumo()["itens_baixos"], 1)  # 3 <= 5, como antes

    def test_rolos_antigos_ganham_o_limite_padrao(self):
        conexao = banco.conectar()
        conexao.executescript("""
            DROP TABLE rolos_tecido;
            CREATE TABLE rolos_tecido (
                id INTEGER PRIMARY KEY AUTOINCREMENT, codigo TEXT UNIQUE,
                tipo_tecido TEXT NOT NULL, cor TEXT NOT NULL,
                metragem_atual REAL NOT NULL DEFAULT 0 CHECK (metragem_atual >= 0),
                ativo INTEGER NOT NULL DEFAULT 1
            );
            INSERT INTO rolos_tecido (codigo, tipo_tecido, cor, metragem_atual)
            VALUES ('RL-000001', 'Malha', 'Azul', 2.5);
        """)
        conexao.close()

        banco.criar_tabelas()

        self.assertEqual(banco.buscar_rolo("RL-000001")["limite_baixo"], banco.LIMITE_METROS_BAIXO)
        self.assertEqual(banco.resumo()["itens_baixos"], 1)  # 2,5 <= 3, como antes


class TesteLimiteNasPaginas(TesteComCliente):

    def test_cadastrar_pela_janela_com_limite(self):
        self.admin.post("/produtos", data={"modelo": "Floral", "tamanho": "M", "cor": "Azul",
                                           "quantidade": "10", "limite_baixo": "25"})
        self.assertEqual(banco.buscar_produto("PJ-FLO-M-AZ")["limite_baixo"], 25)

    def test_limite_invalido_reabre_a_janela_com_mensagem(self):
        html = self.admin.post("/produtos", data={"modelo": "Floral", "tamanho": "M", "cor": "Azul",
                                                  "quantidade": "1", "limite_baixo": "-2"}
                               ).get_data(as_text=True)
        self.assertIn("não pode ser negativo", html)
        self.assertIn("data-abrir", html)
        self.assertIsNone(banco.buscar_produto("PJ-FLO-M-AZ"))

    def test_editar_limite_pela_pagina(self):
        codigo = banco.cadastrar_produto("Floral", "M", "Azul", "10", ADMIN)
        html = self.admin.get(f"/itens/{codigo}/editar").get_data(as_text=True)
        self.assertIn('name="limite_baixo"', html)

        self.admin.post(f"/itens/{codigo}/editar", data={"modelo": "Floral", "tamanho": "M",
                                                         "cor": "Azul", "limite_baixo": "30"})
        self.assertEqual(banco.buscar_produto(codigo)["limite_baixo"], 30)

    def test_operador_nao_altera_o_limite(self):
        codigo = banco.cadastrar_produto("Floral", "M", "Azul", "10", ADMIN)
        resposta = self.operador.post(f"/itens/{codigo}/editar", data={
            "modelo": "Floral", "tamanho": "M", "cor": "Azul", "limite_baixo": "30"})
        self.assertEqual(resposta.status_code, 403)
        self.assertEqual(banco.buscar_produto(codigo)["limite_baixo"], banco.LIMITE_PIJAMAS_BAIXO)

    def test_painel_recebe_o_limite_de_cada_pijama(self):
        banco.cadastrar_produto("Floral", "M", "Azul", "10", ADMIN, limite_baixo="20")
        dados = self.operador.get("/api/painel").get_json()
        self.assertEqual(dados["produtos"][0]["limite_baixo"], 20)
        self.assertEqual(dados["resumo"]["itens_baixos"], 1)

    def test_relatorio_mostra_o_limite(self):
        banco.cadastrar_produto("Floral", "M", "Azul", "10", ADMIN, limite_baixo="20")
        html = self.operador.get("/relatorios").get_data(as_text=True)
        self.assertIn("PJ-FLO-M-AZ", html)
        self.assertIn("Baixo com até", html)

    def test_csv_de_pijamas_tem_o_limite(self):
        banco.cadastrar_produto("Floral", "M", "Azul", "10", ADMIN, limite_baixo="20")
        linhas = self.operador.get("/exportar/pijamas.csv").get_data(as_text=True).splitlines()
        self.assertIn("Estoque baixo com até", linhas[0])
        self.assertEqual(linhas[1].split(";")[5], "20")

    def test_cadastrar_rolo_pela_janela_com_limite(self):
        self.admin.post("/rolos", data={"tipo_tecido": "Malha", "cor": "Azul",
                                        "metragem": "50", "limite_baixo": "8.5"})
        self.assertEqual(banco.buscar_rolo("RL-000001")["limite_baixo"], 8.5)

    def test_editar_limite_do_rolo_pela_pagina(self):
        codigo = banco.cadastrar_rolo("Malha", "Azul", "50", ADMIN)
        html = self.admin.get(f"/itens/{codigo}/editar").get_data(as_text=True)
        self.assertIn("Quase acabando com até", html)

        self.admin.post(f"/itens/{codigo}/editar", data={"tipo_tecido": "Malha", "cor": "Azul",
                                                         "limite_baixo": "9"})
        self.assertEqual(banco.buscar_rolo(codigo)["limite_baixo"], 9)

    def test_painel_e_relatorio_usam_o_limite_do_rolo(self):
        banco.cadastrar_rolo("Malha", "Azul", "8", ADMIN, limite_baixo="10")
        dados = self.operador.get("/api/painel").get_json()
        self.assertEqual(dados["rolos"][0]["limite_baixo"], 10)
        self.assertEqual(dados["resumo"]["itens_baixos"], 1)
        self.assertIn("RL-000001", self.operador.get("/relatorios").get_data(as_text=True))

    def test_csv_de_rolos_tem_o_limite(self):
        banco.cadastrar_rolo("Malha", "Azul", "8", ADMIN, limite_baixo="10,5")
        linhas = self.operador.get("/exportar/tecidos.csv").get_data(as_text=True).splitlines()
        self.assertIn("Quase acabando com até (m)", linhas[0])
        self.assertEqual(linhas[1].split(";")[4], "10,50")


if __name__ == "__main__":
    unittest.main()
