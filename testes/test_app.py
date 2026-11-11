"""Testes das rotas (app.py), usando o "cliente de teste" do Flask.

O cliente de teste faz pedidos ao sistema como se fosse um navegador
(inclusive guardando o cookie de login), mas sem precisar ligar o servidor.
"""

import unittest

import backup
import banco
import usuarios
from testes import ADMIN, SENHA_PADRAO, TesteComBancoLimpo, TesteComCliente


class TestePrimeiroAcesso(TesteComBancoLimpo):

    def setUp(self):
        super().setUp()
        from app import app
        self.cliente = app.test_client()

    def test_sem_usuarios_manda_para_primeiro_acesso(self):
        resposta = self.cliente.get("/")
        self.assertTrue(resposta.location.endswith("/primeiro-acesso"))

    def test_primeiro_acesso_cria_admin_e_ja_entra(self):
        resposta = self.cliente.post("/primeiro-acesso", data={
            "nome": "Dona", "login": "dona", "senha": SENHA_PADRAO, "confirmacao": SENHA_PADRAO,
        })
        self.assertEqual(resposta.status_code, 302)
        self.assertEqual(usuarios.autenticar("dona", SENHA_PADRAO)["perfil"], "admin")
        self.assertEqual(self.cliente.get("/").status_code, 200)  # já está logado

    def test_primeiro_acesso_fecha_depois_que_existe_usuario(self):
        usuarios.criar_usuario("Dona", "dona", SENHA_PADRAO, "admin")
        self.cliente.post("/primeiro-acesso", data={
            "nome": "Intruso", "login": "intruso", "senha": SENHA_PADRAO, "confirmacao": SENHA_PADRAO,
        })
        self.assertIsNone(usuarios.autenticar("intruso", SENHA_PADRAO))


class TesteLogin(TesteComCliente):

    def test_sem_login_paginas_redirecionam_e_api_responde_401(self):
        anonimo = self.app.test_client()
        resposta = anonimo.get("/bipar")
        self.assertEqual(resposta.status_code, 302)
        self.assertIn("/login?proximo=/bipar", resposta.location)
        self.assertEqual(anonimo.get("/api/painel").status_code, 401)

    def test_senha_errada_nao_entra(self):
        anonimo = self.app.test_client()
        resposta = anonimo.post("/login", data={"login": "ana", "senha": "errada"})
        self.assertEqual(resposta.status_code, 200)  # volta para a tela de login
        self.assertEqual(anonimo.get("/").status_code, 302)

    def test_depois_do_login_volta_para_a_pagina_pedida(self):
        anonimo = self.app.test_client()
        resposta = anonimo.post("/login", data={"login": "ana", "senha": SENHA_PADRAO, "proximo": "/rolos"})
        self.assertTrue(resposta.location.endswith("/rolos"))

    def test_login_nao_redireciona_para_outro_site(self):
        for perigoso in ["//site-falso.com", "https://site-falso.com", "/\\site-falso.com"]:
            with self.subTest(proximo=perigoso):
                anonimo = self.app.test_client()
                resposta = anonimo.post("/login", data={
                    "login": "ana", "senha": SENHA_PADRAO, "proximo": perigoso,
                })
                self.assertEqual(resposta.location, "/")

    def test_sair_encerra_o_login(self):
        self.admin.post("/sair")
        self.assertEqual(self.admin.get("/").status_code, 302)

    def test_usuario_desativado_perde_o_acesso_na_hora(self):
        otto = usuarios.autenticar("otto", SENHA_PADRAO)
        ana = usuarios.autenticar("ana", SENHA_PADRAO)
        usuarios.alterar_usuario(otto["id"], "operador", ativo=False, quem_alterou=ana)
        self.assertEqual(self.operador.get("/").status_code, 302)


class TestePermissoes(TesteComCliente):

    def test_operador_nao_cadastra_nem_administra(self):
        resposta = self.operador.post("/produtos", data={"modelo": "X", "tamanho": "M", "cor": "Azul"})
        self.assertEqual(resposta.status_code, 403)
        self.assertEqual(self.operador.get("/admin").status_code, 403)
        self.assertEqual(banco.listar_produtos(), [])

    def test_operador_nao_ve_o_formulario_de_cadastro(self):
        for pagina in ["/produtos", "/rolos"]:
            with self.subTest(pagina=pagina):
                self.assertNotIn("modal-cadastro", self.operador.get(pagina).get_data(as_text=True))
                self.assertIn("modal-cadastro", self.admin.get(pagina).get_data(as_text=True))

    def test_operador_bipa_e_fica_registrado(self):
        codigo = banco.cadastrar_produto("Floral", "M", "Azul", "5", ADMIN)
        resposta = self.operador.post("/api/movimentar", json={
            "codigo": codigo, "tipo": "saida", "quantidade": 1, "motivo": "venda",
        })
        self.assertEqual(resposta.get_json()["item"]["saldo"], 4)
        self.assertEqual(banco.listar_movimentacoes(limite=1)[0]["usuario"], "otto")

    def test_operador_nao_faz_ajuste_pela_api(self):
        codigo = banco.cadastrar_produto("Floral", "M", "Azul", "5", ADMIN)
        resposta = self.operador.post("/api/movimentar", json={
            "codigo": codigo, "tipo": "saida", "quantidade": 1, "motivo": "ajuste",
        })
        self.assertEqual(resposta.status_code, 400)


class TesteApi(TesteComCliente):

    def setUp(self):
        super().setUp()
        self.pijama = banco.cadastrar_produto("Floral", "M", "Azul", "5", ADMIN)

    def movimentar(self, **dados):
        return self.admin.post("/api/movimentar", json=dados)

    def test_movimentar_devolve_saldo_novo(self):
        resposta = self.movimentar(codigo=self.pijama, tipo="saida", quantidade=2, motivo="venda")
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.get_json()["item"]["saldo"], 3)

    def test_erro_de_regra_devolve_400_com_mensagem(self):
        resposta = self.movimentar(codigo=self.pijama, tipo="saida", quantidade=99, motivo="venda")
        self.assertEqual(resposta.status_code, 400)
        self.assertIn("insuficiente", resposta.get_json()["erro"])

    def test_pedido_sem_json_nao_quebra(self):
        self.assertEqual(self.admin.post("/api/movimentar", data="lixo").status_code, 400)

    def test_item_inexistente_e_desativado(self):
        self.assertEqual(self.admin.get("/api/item/NAOEXISTE").status_code, 404)
        banco.definir_item_ativo(self.pijama, False)
        self.assertEqual(self.admin.get(f"/api/item/{self.pijama}").status_code, 400)

    def test_painel_traz_todas_as_partes(self):
        dados = self.admin.get("/api/painel").get_json()
        for chave in ["resumo", "produtos", "rolos", "movimentacoes", "limites"]:
            self.assertIn(chave, dados)


class TestePaginas(TesteComCliente):

    def test_todas_as_paginas_abrem(self):
        banco.cadastrar_produto("Floral", "M", "Azul", "5", ADMIN)
        for endereco in ["/", "/bipar", "/produtos", "/rolos", "/movimentacoes", "/relatorios",
                         "/etiquetas?codigo=PJ-FLO-M-AZ", "/itens/PJ-FLO-M-AZ/editar", "/admin", "/minha-senha"]:
            with self.subTest(endereco=endereco):
                self.assertEqual(self.admin.get(endereco).status_code, 200)

    def test_codigo_inexistente_mostra_pagina_404(self):
        resposta = self.admin.get("/itens/NAOEXISTE/editar")
        self.assertEqual(resposta.status_code, 404)
        self.assertIn("não existe", resposta.get_data(as_text=True))

    def test_cadastro_volta_para_a_lista_com_o_item_ja_marcado(self):
        resposta = self.admin.post("/rolos", data={"tipo_tecido": "Malha", "cor": "Azul", "metragem": "50"})
        self.assertEqual(resposta.status_code, 302)
        self.assertTrue(resposta.location.endswith("/rolos?novo=RL-000001"))
        self.assertEqual(banco.listar_movimentacoes(limite=1)[0]["usuario"], "ana")

        html = self.admin.get(resposta.location).get_data(as_text=True)
        self.assertRegex(html, r'value="RL-000001"\s+form="form-etiquetas"[^>]*\s+checked')

    def test_cadastro_com_erro_reabre_o_modal_com_o_que_foi_digitado(self):
        resposta = self.admin.post("/produtos", data={"modelo": "Floral", "tamanho": "M", "cor": "Azul",
                                                      "codigo": "RL-000001"})  # prefixo reservado
        html = resposta.get_data(as_text=True)
        self.assertEqual(resposta.status_code, 200)
        self.assertIn("data-abrir", html)
        self.assertIn('value="Floral"', html)
        self.assertEqual(banco.listar_produtos(), [])

    def test_operador_nao_recebe_o_modal_de_cadastro(self):
        html = self.operador.get("/produtos").get_data(as_text=True)
        self.assertNotIn("modal-cadastro", html)
        # mas pode gerar etiquetas, nos dois formatos
        self.assertIn("Gerar código de barras", html)
        self.assertIn("Gerar QR code", html)

    def test_editar_e_desativar_pelas_paginas(self):
        codigo = banco.cadastrar_produto("Floral", "M", "Azul", "5", ADMIN)
        self.admin.post(f"/itens/{codigo}/editar", data={"modelo": "Floral Novo", "tamanho": "M", "cor": "Azul"})
        self.assertEqual(banco.buscar_produto(codigo)["modelo"], "Floral Novo")

        self.admin.post(f"/itens/{codigo}/ativo", data={"ativo": "0"})
        self.assertEqual(banco.buscar_produto(codigo)["ativo"], 0)
        self.assertEqual(self.operador.post(f"/itens/{codigo}/ativo", data={"ativo": "1"}).status_code, 403)

    def test_numeros_e_datas_no_formato_brasileiro(self):
        banco.cadastrar_rolo("Malha", "Azul", "1234.5", ADMIN)
        self.assertIn("1.234,50", self.admin.get("/rolos").get_data(as_text=True))
        self.assertRegex(self.admin.get("/movimentacoes").get_data(as_text=True),
                         r"\d{2}/\d{2}/\d{4} \d{2}:\d{2}")

    def test_imagem_do_codigo_de_barras(self):
        resposta = self.admin.get("/codigo-barras/PJ-FLO-M-AZ.png")
        self.assertEqual(resposta.mimetype, "image/png")


class TesteEtiquetas(TesteComCliente):

    def setUp(self):
        super().setUp()
        self.pijama = banco.cadastrar_produto("Floral", "M", "Azul", "5", ADMIN)
        self.rolo = banco.cadastrar_rolo("Malha", "Azul", "50", ADMIN)

    def contar_etiquetas(self, endereco):
        return self.operador.get(endereco).get_data(as_text=True).count('class="etiqueta"')

    def test_varios_itens_com_copias_diferentes(self):
        endereco = f"/etiquetas?codigo={self.pijama}&copias=3&codigo={self.rolo}&copias=2"
        self.assertEqual(self.contar_etiquetas(endereco), 5)

    def test_sem_copias_imprime_uma_de_cada(self):
        self.assertEqual(self.contar_etiquetas(f"/etiquetas?codigo={self.pijama}&codigo={self.rolo}"), 2)

    def test_copias_invalidas_viram_numeros_seguros(self):
        endereco = f"/etiquetas?codigo={self.pijama}&copias=abc&codigo={self.rolo}&copias=99999"
        self.assertEqual(self.contar_etiquetas(endereco), 1 + 100)  # "abc" -> 1; 99999 -> 100

    def test_codigo_repetido_ou_inexistente_e_ignorado(self):
        endereco = f"/etiquetas?codigo={self.pijama}&codigo={self.pijama}&codigo=NAOEXISTE"
        self.assertEqual(self.contar_etiquetas(endereco), 1)

    def test_sem_nenhum_item_volta_com_aviso(self):
        resposta = self.admin.get("/etiquetas")
        self.assertEqual(resposta.status_code, 302)


class TesteExportacao(TesteComCliente):

    def test_csv_abre_certo_no_excel(self):
        rolo = banco.cadastrar_rolo("Algodão", "Azul", "12,5", ADMIN)
        resposta = self.operador.get("/exportar/tecidos.csv")
        texto = resposta.get_data(as_text=True)

        self.assertEqual(resposta.mimetype, "text/csv")
        self.assertIn("attachment", resposta.headers["Content-Disposition"])
        self.assertTrue(texto.startswith("﻿"))         # BOM: acentos certos no Excel
        self.assertIn(f"{rolo};Algodão;Azul;12,50;Ativo", texto)  # ; e vírgula decimal

    def test_csv_nao_deixa_executar_formula(self):
        banco.cadastrar_produto("=HIPERLINK(1)", "M", "Azul", "1", ADMIN, codigo="PJ-TESTE")
        texto = self.admin.get("/exportar/pijamas.csv").get_data(as_text=True)
        self.assertIn("'=HIPERLINK(1)", texto)

    def test_todos_os_csv_existem(self):
        for relatorio in ["pijamas", "tecidos", "movimentacoes", "consumo-tecido", "vendas"]:
            with self.subTest(relatorio=relatorio):
                self.assertEqual(self.admin.get(f"/exportar/{relatorio}.csv").status_code, 200)
        self.assertEqual(self.admin.get("/exportar/qualquer-coisa.csv").status_code, 404)


class TesteBackup(TesteComCliente):

    def test_backup_pela_tela_e_download(self):
        banco.cadastrar_produto("Floral", "M", "Azul", "5", ADMIN)
        self.admin.post("/admin/backups")
        backups = backup.listar_backups()
        self.assertEqual(len(backups), 1)

        resposta = self.admin.get(f"/admin/backups/{backups[0]['nome']}")
        self.assertEqual(resposta.status_code, 200)
        self.assertTrue(resposta.data.startswith(b"SQLite format 3"))  # é um banco de verdade
        resposta.close()

    def test_download_nao_aceita_outros_arquivos(self):
        for nome in ["app.py", "..%2Fapp.py", "estoque.db"]:
            with self.subTest(nome=nome):
                self.assertEqual(self.admin.get(f"/admin/backups/{nome}").status_code, 404)

    def test_operador_nao_mexe_em_backup(self):
        self.assertEqual(self.operador.post("/admin/backups").status_code, 403)

    def test_guarda_so_os_mais_recentes(self):
        original = backup.QUANTIDADE_A_MANTER
        backup.QUANTIDADE_A_MANTER = 2
        try:
            nomes = []
            for segundo in range(3):
                # nomes com datas diferentes, para não depender do relógio
                nome = f"estoque_2026-01-0{segundo + 1}_120000.db"
                backup.PASTA_BACKUPS.mkdir(parents=True, exist_ok=True)
                (backup.PASTA_BACKUPS / nome).write_bytes(b"x")
                nomes.append(nome)
            backup._apagar_backups_antigos()
            restantes = [b["nome"] for b in backup.listar_backups()]
            self.assertEqual(restantes, [nomes[2], nomes[1]])
        finally:
            backup.QUANTIDADE_A_MANTER = original


if __name__ == "__main__":
    unittest.main()
