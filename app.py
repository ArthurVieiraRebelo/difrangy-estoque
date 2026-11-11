"""
app.py
------
As rotas (endereços) do sistema. Cada função aqui responde a um endereço.

- Rotas de PÁGINA devolvem HTML (render_template).
- Rotas de API (começam com /api) devolvem JSON. Elas são chamadas pelo
  JavaScript com fetch(), sem recarregar a página.

Para rodar (dentro da pasta Difrangy):
    .venv/bin/python app.py          (Linux)
    .venv\\Scripts\\python app.py      (Windows)

Para rodar os testes:
    .venv/bin/python -m unittest -v
"""

import os
import secrets
import socket
from datetime import date, timedelta
from pathlib import Path

from flask import (Flask, Response, abort, flash, g, jsonify, redirect,
                   render_template, request, send_from_directory, session, url_for)
from waitress import serve

import backup
import banco
import configuracoes
import exportacao
import usuarios
from etiquetas import gerar_png_codigo_barras, gerar_png_qrcode

PASTA_DO_PROJETO = Path(__file__).parent
# Porta do sistema. Dá para trocar com a variável de ambiente ESTOQUE_PORTA
# (útil para rodar uma cópia de teste sem atrapalhar o sistema em uso).
PORTA = int(os.environ.get("ESTOQUE_PORTA", 5000))


def carregar_chave_secreta():
    """A chave secreta "assina" o cookie de login, para ninguém conseguir
    falsificar que está logado. Ela precisa ser a mesma sempre — se mudasse
    a cada vez que o sistema reinicia, todo mundo seria deslogado.

    Na primeira vez, sorteamos uma chave e guardamos no arquivo .chave_secreta
    (que fica fora do Git). Nas próximas, lemos do arquivo.
    """
    if os.environ.get("CHAVE_SECRETA"):
        return os.environ["CHAVE_SECRETA"]
    arquivo = PASTA_DO_PROJETO / ".chave_secreta"
    if not arquivo.exists():
        arquivo.write_text(secrets.token_hex(32))
    return arquivo.read_text().strip()


app = Flask(__name__)
app.secret_key = carregar_chave_secreta()
app.permanent_session_lifetime = timedelta(hours=12)  # o login dura um turno
# SameSite=Lax: o navegador NÃO envia o cookie de login quando outro site
# tenta enviar um formulário para cá. Protege contra o ataque chamado CSRF.
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

# Cria as tabelas (se ainda não existirem) assim que o sistema inicia
banco.criar_tabelas()


# =====================================================================
# Login e permissões
# =====================================================================

# Páginas que podem ser abertas sem estar logado
PAGINAS_LIVRES = {"login", "primeiro_acesso", "static"}


@app.before_request
def exigir_login():
    """Roda ANTES de toda página. Descobre quem está logado e guarda em g.usuario.

    "g" é um objeto do Flask que vale só durante o pedido atual — serve para
    as rotas e os templates saberem quem é o usuário.
    """
    g.usuario = None
    id_usuario = session.get("usuario_id")
    if id_usuario:
        usuario = usuarios.buscar_por_id(id_usuario)
        if usuario and usuario["ativo"]:
            g.usuario = usuario
        else:
            session.clear()  # usuário foi desativado: derruba o login dele

    if g.usuario or request.endpoint in PAGINAS_LIVRES:
        return None  # None = pode seguir para a página pedida

    if usuarios.contar_usuarios() == 0:
        return redirect(url_for("primeiro_acesso"))
    if request.path.startswith("/api/"):
        # O JavaScript recebe 401 e manda o funcionário para a tela de login
        return jsonify(ok=False, erro="Sua sessão expirou. Entre de novo no sistema."), 401
    return redirect(url_for("login", proximo=request.full_path.rstrip("?")))


def exigir_admin():
    """Chame no começo de qualquer ação que só o administrador pode fazer."""
    if g.usuario["perfil"] != "admin":
        abort(403)  # 403 = "proibido"


def exigir_master():
    """Chame no começo de qualquer ação que só o master (dono do sistema) pode fazer."""
    if not usuarios.eh_master(g.usuario):
        abort(403)


def entrar(usuario):
    session.clear()  # começa uma sessão nova (boa prática de segurança)
    session["usuario_id"] = usuario["id"]
    session.permanent = True  # vale pelo tempo de permanent_session_lifetime


def endereco_seguro(proximo):
    """Depois do login voltamos para a página que a pessoa queria abrir.
    Só aceitamos endereços DESTE sistema ("/bipar"), nunca "//outro-site.com",
    senão um link malicioso poderia mandar o funcionário para um site falso."""
    if proximo and proximo.startswith("/") and not proximo.startswith("//") and "\\" not in proximo:
        return proximo
    return url_for("painel")


@app.context_processor
def variaveis_para_todos_os_templates():
    """Tudo que esta função devolve fica disponível em TODOS os templates."""
    usuario = g.get("usuario")
    return {
        "MOTIVOS": banco.MOTIVOS,
        "PERFIS": usuarios.PERFIS,
        "eh_admin": bool(usuario) and usuario["perfil"] == "admin",
        "eh_master": usuarios.eh_master(usuario),
    }


@app.route("/login", methods=["GET", "POST"])
def login():
    if usuarios.contar_usuarios() == 0:
        return redirect(url_for("primeiro_acesso"))
    proximo = request.values.get("proximo", "")
    if request.method == "POST":
        usuario = usuarios.autenticar(request.form.get("login"), request.form.get("senha"))
        if usuario:
            entrar(usuario)
            return redirect(endereco_seguro(proximo))
        # Mensagem genérica de propósito: não dizemos se foi o login ou a senha
        flash("Login ou senha incorretos.", "erro")
    return render_template("login.html", proximo=proximo)


@app.route("/sair", methods=["POST"])
def sair():
    session.clear()
    flash("Você saiu do sistema.", "sucesso")
    return redirect(url_for("login"))


@app.route("/primeiro-acesso", methods=["GET", "POST"])
def primeiro_acesso():
    """Só funciona enquanto não existe nenhum usuário: cria o primeiro administrador."""
    if usuarios.contar_usuarios() > 0:
        return redirect(url_for("login"))
    if request.method == "POST":
        formulario = request.form
        try:
            if formulario.get("senha") != formulario.get("confirmacao"):
                raise usuarios.ErroUsuario("A senha e a confirmação não são iguais.")
            login_criado = usuarios.criar_usuario(
                formulario.get("nome"), formulario.get("login"), formulario.get("senha"), "admin",
                master=True,  # quem faz o primeiro acesso é o dono do sistema
            )
        except usuarios.ErroUsuario as erro:
            flash(str(erro), "erro")
        else:
            entrar(usuarios.autenticar(login_criado, formulario.get("senha")))
            flash("Administrador criado. Bem-vindo ao sistema!", "sucesso")
            return redirect(url_for("painel"))
    return render_template("primeiro_acesso.html")


@app.route("/minha-senha", methods=["GET", "POST"])
def minha_senha():
    if request.method == "POST":
        try:
            usuarios.trocar_propria_senha(
                g.usuario, request.form.get("senha_atual"),
                request.form.get("nova_senha"), request.form.get("confirmacao"),
            )
        except usuarios.ErroUsuario as erro:
            flash(str(erro), "erro")
        else:
            flash("Senha alterada.", "sucesso")
            return redirect(url_for("painel"))
    return render_template("minha_senha.html")


# =====================================================================
# Filtros dos templates
# =====================================================================
# Um filtro é usado no HTML assim: {{ valor|numero_br(2) }}
# Eles deixam as páginas no mesmo formato que o JavaScript usa no painel.

@app.template_filter("numero_br")
def numero_br(valor, casas=0):
    """22.2 -> '22,20' (com casas=2); 1500 -> '1.500'."""
    texto = f"{float(valor):,.{casas}f}"  # formato americano: 1,500.00
    # Troca os separadores: vírgula vira ponto e ponto vira vírgula
    return texto.replace(",", "_").replace(".", ",").replace("_", ".")


@app.template_filter("data_br")
def data_br(texto):
    """'2026-11-09 14:30:05' -> '09/11/2026 14:30'"""
    data, hora = texto.split(" ")
    ano, mes, dia = data.split("-")
    return f"{dia}/{mes}/{ano} {hora[:5]}"


@app.template_filter("mes_br")
def mes_br(texto):
    """'2026-11' -> '11/2026'"""
    ano, mes = texto.split("-")
    return f"{mes}/{ano}"


# =====================================================================
# Páginas do estoque
# =====================================================================

@app.route("/")
def painel():
    # O painel começa vazio; o JavaScript (painel.js) busca os dados em /api/painel
    return render_template("painel.html")


@app.route("/bipar")
def bipar():
    # O operador não recebe o motivo "ajuste" (só o administrador pode usar)
    return render_template(
        "bipar.html", motivos_permitidos=banco.motivos_permitidos_para(g.usuario["perfil"])
    )


@app.route("/produtos", methods=["GET", "POST"])
def produtos():
    formulario = {}
    abrir_modal = False
    if request.method == "POST":
        exigir_admin()
        formulario = request.form
        try:
            codigo = banco.cadastrar_produto(
                modelo=formulario.get("modelo", ""),
                tamanho=formulario.get("tamanho", ""),
                cor=formulario.get("cor", ""),
                quantidade_inicial=formulario.get("quantidade", "0"),
                usuario=g.usuario,
                codigo=formulario.get("codigo", ""),
            )
        except banco.ErroEstoque as erro:
            flash(str(erro), "erro")
            # Não redireciona: mostra a página de novo com a janela de cadastro
            # aberta e o que foi digitado, para só corrigir o campo errado.
            abrir_modal = True
        else:
            flash(f"Pijama {codigo} cadastrado e já marcado na lista. "
                  "Clique em “Gerar etiquetas” para imprimir.", "sucesso")
            # Depois de um POST que deu certo, redirecionamos (padrão Post/Redirect/Get):
            # assim, se apertar F5, o navegador não reenvia o formulário.
            # "novo" faz a lista já vir com o item recém-cadastrado marcado.
            return redirect(url_for("produtos", novo=codigo))

    return render_template(
        "produtos.html",
        produtos=banco.listar_produtos(),
        modelos=banco.listar_valores_distintos("modelo"),
        cores=banco.listar_valores_distintos("cor_produto"),
        formulario=formulario,
        abrir_modal=abrir_modal,
        novo=request.args.get("novo", ""),
        # Botões de etiqueta que o master deixou ligados (código de barras, QR code)
        tipos_etiqueta=configuracoes.tipos_de_etiqueta_liberados(),
    )


@app.route("/rolos", methods=["GET", "POST"])
def rolos():
    formulario = {}
    abrir_modal = False
    if request.method == "POST":
        exigir_admin()
        formulario = request.form
        try:
            codigo = banco.cadastrar_rolo(
                tipo_tecido=formulario.get("tipo_tecido", ""),
                cor=formulario.get("cor", ""),
                metragem=formulario.get("metragem", ""),
                usuario=g.usuario,
            )
        except banco.ErroEstoque as erro:
            flash(str(erro), "erro")
            abrir_modal = True
        else:
            flash(f"Rolo {codigo} cadastrado e já marcado na lista. "
                  "Clique em “Gerar etiquetas” para imprimir e cole a etiqueta no rolo.", "sucesso")
            return redirect(url_for("rolos", novo=codigo))

    return render_template(
        "rolos.html",
        rolos=banco.listar_rolos(),
        tipos=banco.listar_valores_distintos("tipo_tecido"),
        cores=banco.listar_valores_distintos("cor_rolo"),
        formulario=formulario,
        abrir_modal=abrir_modal,
        novo=request.args.get("novo", ""),
        # Botões de etiqueta que o master deixou ligados (código de barras, QR code)
        tipos_etiqueta=configuracoes.tipos_de_etiqueta_liberados(),
    )


def pagina_da_lista(item):
    """Endereço da lista onde o item aparece (pijamas ou tecidos)."""
    return url_for("produtos") if item["tipo_item"] == "produto" else url_for("rolos")


@app.route("/itens/<codigo>/editar", methods=["GET", "POST"])
def editar_item(codigo):
    exigir_admin()
    item = banco.buscar_item(codigo)
    if item is None:
        abort(404)

    if request.method == "POST":
        formulario = request.form
        try:
            if item["tipo_item"] == "produto":
                banco.editar_produto(item["codigo"], formulario.get("modelo"),
                                     formulario.get("tamanho"), formulario.get("cor"))
            else:
                banco.editar_rolo(item["codigo"], formulario.get("tipo_tecido"), formulario.get("cor"))
        except banco.ErroEstoque as erro:
            flash(str(erro), "erro")
        else:
            flash(f"{item['codigo']} atualizado.", "sucesso")
            return redirect(pagina_da_lista(item))

    return render_template("editar_item.html", item=item)


@app.route("/itens/<codigo>/ativo", methods=["POST"])
def ativar_desativar_item(codigo):
    exigir_admin()
    ativar = request.form.get("ativo") == "1"
    try:
        item = banco.definir_item_ativo(codigo, ativar)
    except banco.ErroEstoque as erro:
        flash(str(erro), "erro")
        return redirect(url_for("painel"))
    flash(f"{item['codigo']} {'reativado' if ativar else 'desativado'}.", "sucesso")
    return redirect(pagina_da_lista(item))


@app.route("/itens/<codigo>/excluir", methods=["POST"])
def excluir_item(codigo):
    """Exclui de vez um item que já esteja desativado (regra em banco.excluir_item)."""
    exigir_admin()
    try:
        item = banco.excluir_item(codigo)
    except banco.ErroEstoque as erro:
        flash(str(erro), "erro")
        return redirect(url_for("editar_item", codigo=codigo))
    flash(f"{item['codigo']} excluído. O histórico de movimentações dele continua guardado.", "sucesso")
    return redirect(pagina_da_lista(item))


@app.route("/movimentacoes")
def movimentacoes():
    # request.args = parâmetros da URL, ex: /movimentacoes?codigo=PJ-FLO-M-AZ
    codigo = request.args.get("codigo", "").strip().upper()
    return render_template(
        "movimentacoes.html",
        movimentacoes=banco.listar_movimentacoes(limite=500, codigo=codigo),
        codigo=codigo,
    )


@app.route("/relatorios")
def relatorios():
    return render_template(
        "relatorios.html",
        pijamas_baixos=banco.relatorio_pijamas_baixos(),
        rolos_acabando=banco.relatorio_rolos_acabando(),
        consumo_tecido=banco.relatorio_consumo_tecido_por_mes(),
        vendas=banco.relatorio_pijamas_vendidos_por_mes(),
        limite_pijamas=banco.LIMITE_PIJAMAS_BAIXO,
        limite_metros=banco.LIMITE_METROS_BAIXO,
    )


MAXIMO_COPIAS_POR_ITEM = 100
MAXIMO_ITENS_POR_VEZ = 100


def converter_copias(texto):
    """Número de cópias digitado -> inteiro entre 1 e MAXIMO_COPIAS_POR_ITEM.
    Se vier algo que não é número, usa 1."""
    try:
        copias = int(texto)
    except (TypeError, ValueError):
        return 1
    return max(1, min(copias, MAXIMO_COPIAS_POR_ITEM))


@app.route("/etiquetas")
def etiquetas():
    """Página de impressão das etiquetas dos itens marcados nas listas.

    O endereço traz o TIPO de etiqueta ("barras" ou "qr"), os códigos e,
    opcionalmente, as cópias de cada um, na mesma ordem:
        /etiquetas?tipo=qr&codigo=PJ-FLO-M-AZ&copias=3&codigo=RL-000001&copias=1

    getlist() pega TODOS os valores com o mesmo nome (o get() pegaria só o primeiro).
    """
    tipo = request.args.get("tipo", "barras")
    # Confere no servidor também: esconder o botão não basta, alguém poderia
    # digitar o endereço direto no navegador.
    if not configuracoes.etiqueta_liberada(tipo):
        flash("Este tipo de etiqueta está desligado nas configurações do sistema.", "erro")
        return redirect(url_for("produtos"))

    codigos = request.args.getlist("codigo")[:MAXIMO_ITENS_POR_VEZ]
    copias_digitadas = request.args.getlist("copias")

    selecionados = []
    ja_incluidos = set()  # para não repetir o mesmo item se vier duas vezes
    for posicao, codigo in enumerate(codigos):
        item = banco.buscar_item(codigo)
        if item is None or item["codigo"] in ja_incluidos:
            continue
        # Se não veio o número de cópias deste item, imprime 1
        texto_copias = copias_digitadas[posicao] if posicao < len(copias_digitadas) else "1"
        item["copias"] = converter_copias(texto_copias)
        selecionados.append(item)
        ja_incluidos.add(item["codigo"])

    if not selecionados:
        flash("Marque pelo menos um item na lista para gerar etiquetas.", "erro")
        return redirect(url_for("produtos"))

    total = sum(item["copias"] for item in selecionados)
    return render_template(
        "etiquetas.html",
        itens=selecionados,
        total=total,
        tipo=tipo,
        nome_tipo=configuracoes.TIPOS_ETIQUETA[tipo]["nome"],
    )


@app.route("/codigo-barras/<codigo>.png")
def imagem_codigo_barras(codigo):
    """Devolve a IMAGEM do código de barras. É usada no <img> da etiqueta."""
    try:
        codigo = banco.limpar_codigo(codigo)
    except banco.ErroEstoque:
        abort(404)
    return Response(gerar_png_codigo_barras(codigo), mimetype="image/png")


@app.route("/qrcode/<codigo>.png")
def imagem_qrcode(codigo):
    """Devolve a IMAGEM do QR code. É usada no <img> da etiqueta."""
    try:
        codigo = banco.limpar_codigo(codigo)
    except banco.ErroEstoque:
        abort(404)
    return Response(gerar_png_qrcode(codigo), mimetype="image/png")


# =====================================================================
# Exportação (CSV)
# =====================================================================

@app.route("/exportar/<relatorio>.csv")
def exportar(relatorio):
    if relatorio == "pijamas":
        conteudo = exportacao.csv_pijamas(banco.listar_produtos())
    elif relatorio == "tecidos":
        conteudo = exportacao.csv_rolos(banco.listar_rolos())
    elif relatorio == "movimentacoes":
        codigo = request.args.get("codigo", "").strip().upper()
        # No SQLite, LIMIT -1 significa "sem limite": exporta o histórico inteiro
        conteudo = exportacao.csv_movimentacoes(banco.listar_movimentacoes(limite=-1, codigo=codigo))
    elif relatorio == "consumo-tecido":
        conteudo = exportacao.csv_consumo_tecido(banco.relatorio_consumo_tecido_por_mes())
    elif relatorio == "vendas":
        conteudo = exportacao.csv_vendas(banco.relatorio_pijamas_vendidos_por_mes())
    else:
        abort(404)

    nome_arquivo = f"{relatorio}_{date.today():%Y-%m-%d}.csv"
    # Content-Disposition: attachment faz o navegador BAIXAR o arquivo
    return Response(
        conteudo,
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{nome_arquivo}"'},
    )


# =====================================================================
# Administração (usuários e backups) — só administrador
# =====================================================================

@app.route("/admin")
def admin():
    exigir_admin()
    return render_template(
        "admin.html",
        usuarios=usuarios.listar_usuarios(),
        backups=backup.listar_backups(),
        pasta_backups=backup.PASTA_BACKUPS,
        # Para a seção de configurações (que só aparece para o master)
        tipos_etiqueta=configuracoes.TIPOS_ETIQUETA,
        etiqueta_liberada=configuracoes.etiqueta_liberada,
    )


@app.route("/admin/configuracoes", methods=["POST"])
def salvar_configuracoes():
    """Liga/desliga os botões de gerar etiqueta. Só o master pode."""
    exigir_master()
    for tipo, dados in configuracoes.TIPOS_ETIQUETA.items():
        # Caixinha marcada envia o valor "1"; desmarcada não envia nada
        ligado = request.form.get(tipo) == "1"
        configuracoes.definir(dados["chave"], "1" if ligado else "0")
    flash("Configurações salvas.", "sucesso")
    return redirect(url_for("admin"))


@app.route("/admin/usuarios", methods=["POST"])
def criar_usuario():
    exigir_admin()
    formulario = request.form
    try:
        login_criado = usuarios.criar_usuario(
            formulario.get("nome"), formulario.get("login"),
            formulario.get("senha"), formulario.get("perfil"),
        )
    except usuarios.ErroUsuario as erro:
        flash(str(erro), "erro")
    else:
        flash(f"Usuário {login_criado} criado.", "sucesso")
    return redirect(url_for("admin"))


@app.route("/admin/usuarios/<int:id_usuario>", methods=["POST"])
def alterar_usuario(id_usuario):
    exigir_admin()
    try:
        usuarios.alterar_usuario(
            id_usuario,
            perfil=request.form.get("perfil"),
            ativo=request.form.get("ativo") == "1",
            quem_alterou=g.usuario,
        )
    except usuarios.ErroUsuario as erro:
        flash(str(erro), "erro")
    else:
        flash("Usuário atualizado.", "sucesso")
    return redirect(url_for("admin"))


@app.route("/admin/usuarios/<int:id_usuario>/senha", methods=["POST"])
def redefinir_senha(id_usuario):
    """O administrador define uma senha nova para quem esqueceu a sua."""
    exigir_admin()
    try:
        usuarios.redefinir_senha(id_usuario, request.form.get("nova_senha"), quem_alterou=g.usuario)
    except usuarios.ErroUsuario as erro:
        flash(str(erro), "erro")
    else:
        flash("Senha redefinida. Passe a senha nova para o funcionário.", "sucesso")
    return redirect(url_for("admin"))


@app.route("/admin/backups", methods=["POST"])
def fazer_backup_agora():
    exigir_admin()
    flash(f"Backup criado: {backup.fazer_backup()}", "sucesso")
    return redirect(url_for("admin"))


@app.route("/admin/backups/<nome>")
def baixar_backup(nome):
    exigir_admin()
    if not backup.nome_de_backup_valido(nome):
        abort(404)
    return send_from_directory(backup.PASTA_BACKUPS, nome, as_attachment=True)


# =====================================================================
# API (JSON) — usada pelo JavaScript, sem recarregar a página
# =====================================================================

@app.route("/api/item/<codigo>")
def api_item(codigo):
    """Diz o que é o código bipado (pijama ou rolo) e o saldo atual."""
    item = banco.buscar_item(codigo)
    if item is None:
        return jsonify(ok=False, erro=f"Código {codigo.upper()} não encontrado."), 404
    if not item["ativo"]:
        return jsonify(ok=False, erro=f"{item['descricao']} ({item['codigo']}) está desativado."), 400
    return jsonify(ok=True, item=item)


@app.route("/api/movimentar", methods=["POST"])
def api_movimentar():
    """Registra uma entrada ou saída.

    Recebe JSON: {"codigo": "...", "tipo": "saida", "quantidade": 1, "motivo": "venda"}
    """
    dados = request.get_json(silent=True) or {}  # silent: se não vier JSON, usa {}
    try:
        item = banco.registrar_movimentacao(
            codigo=dados.get("codigo", ""),
            tipo=dados.get("tipo", ""),
            quantidade=dados.get("quantidade", ""),
            motivo=dados.get("motivo", ""),
            usuario=g.usuario,
        )
    except banco.ErroEstoque as erro:
        # 400 = "pedido inválido". O JavaScript mostra a mensagem em vermelho.
        return jsonify(ok=False, erro=str(erro)), 400
    return jsonify(ok=True, item=item)


@app.route("/api/painel")
def api_painel():
    """Tudo que o painel mostra. O painel.js chama este endereço a cada 3 segundos."""
    return jsonify(
        resumo=banco.resumo(),
        produtos=banco.listar_produtos(somente_ativos=True),
        rolos=banco.listar_rolos(somente_com_saldo=True, somente_ativos=True),
        movimentacoes=banco.listar_movimentacoes(limite=15),
        limites={"pijamas": banco.LIMITE_PIJAMAS_BAIXO, "metros": banco.LIMITE_METROS_BAIXO},
    )


# =====================================================================
# Páginas de erro
# =====================================================================

@app.errorhandler(403)
def acesso_negado(erro):
    return render_template("erro.html", titulo="Acesso restrito",
                           mensagem="Esta ação é só para administradores."), 403


@app.errorhandler(404)
def nao_encontrado(erro):
    return render_template("erro.html", titulo="Página não encontrada",
                           mensagem="O endereço ou o código pedido não existe."), 404


# =====================================================================
# Iniciar o sistema
# =====================================================================

def descobrir_ip_na_rede():
    """Descobre o IP deste computador na rede local (ex: 192.168.0.15).

    O connect() de um socket UDP não envia nada pela rede: ele só faz o
    sistema operacional escolher qual placa de rede usaria, e lemos o IP dela.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as teste:
            teste.connect(("8.8.8.8", 80))
            return teste.getsockname()[0]
    except OSError:
        return "<IP-deste-computador>"


def porta_esta_livre(porta):
    """Testa se dá para usar a porta. Se o sistema já estiver aberto em outro
    terminal, a porta está ocupada e o bind() dá erro."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as teste:
        try:
            teste.bind(("0.0.0.0", porta))
            return True
        except OSError:
            return False


if __name__ == "__main__":
    if not porta_esta_livre(PORTA):
        print(f"A porta {PORTA} já está em uso: o sistema provavelmente já está aberto em outro terminal.")
        print(f"Use o que já está aberto (http://localhost:{PORTA}) ou feche o outro terminal com Ctrl+C.")
        raise SystemExit(1)  # encerra com código de erro, sem a mensagem técnica do Python

    backup.iniciar_backup_automatico()
    print("Sistema de estoque no ar!")
    print(f"  Neste computador:     http://localhost:{PORTA}")
    print(f"  Nos outros da rede:   http://{descobrir_ip_na_rede()}:{PORTA}")
    # flush=True: mostra o texto na hora (sem isso, se a saída for um arquivo
    # de log, o Python guarda o texto e só escreve depois)
    print("Para desligar, aperte Ctrl+C.", flush=True)
    # Waitress: servidor feito para uso real (o app.run() do Flask é só para
    # desenvolvimento). threads=8: atende até 8 pedidos ao mesmo tempo.
    # host="0.0.0.0": aceita conexões dos outros computadores da rede.
    serve(app, host="0.0.0.0", port=PORTA, threads=8)
