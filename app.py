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
Depois abra:  http://localhost:5000  (neste computador)
         ou:  http://<IP deste computador>:5000  (nos outros computadores da rede)

Para rodar os testes:
    .venv/bin/python -m unittest -v
"""

import os
import secrets

from flask import (Flask, Response, abort, flash, jsonify, redirect,
                   render_template, request, url_for)

import banco
from etiquetas import gerar_png_codigo_barras

app = Flask(__name__)

# O flash() (mensagens tipo "Cadastrado com sucesso") precisa de uma chave secreta.
# Se a variável de ambiente CHAVE_SECRETA não existir, sorteamos uma chave
# aleatória cada vez que o sistema inicia (assim ela nunca fica escrita no código).
app.secret_key = os.environ.get("CHAVE_SECRETA") or secrets.token_hex(32)

# Cria as tabelas (se ainda não existirem) assim que o sistema inicia
banco.criar_tabelas()


@app.context_processor
def variaveis_para_todos_os_templates():
    """Tudo que esta função devolve fica disponível em TODOS os templates.
    Usamos para mostrar o nome do motivo ("Venda") em vez da chave ("venda")."""
    return {"MOTIVOS": banco.MOTIVOS}


# ---------- Filtros dos templates ----------
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
# Páginas
# =====================================================================

@app.route("/")
def painel():
    # O painel começa vazio; o JavaScript (painel.js) busca os dados em /api/painel
    return render_template("painel.html")


@app.route("/bipar")
def bipar():
    return render_template("bipar.html", motivos_permitidos=banco.MOTIVOS_PERMITIDOS)


@app.route("/produtos", methods=["GET", "POST"])
def produtos():
    formulario = {}
    if request.method == "POST":
        formulario = request.form
        try:
            codigo = banco.cadastrar_produto(
                modelo=formulario.get("modelo", ""),
                tamanho=formulario.get("tamanho", ""),
                cor=formulario.get("cor", ""),
                quantidade_inicial=formulario.get("quantidade", "0"),
                codigo=formulario.get("codigo", ""),
            )
        except banco.ErroEstoque as erro:
            flash(str(erro), "erro")
            # Não redireciona: mostra a página de novo com o que foi digitado
        else:
            flash(f"Pijama cadastrado com o código {codigo}. Imprima a etiqueta abaixo.", "sucesso")
            # Depois de um POST que deu certo, redirecionamos (padrão Post/Redirect/Get):
            # assim, se apertar F5, o navegador não reenvia o formulário.
            return redirect(url_for("etiqueta", codigo=codigo))

    return render_template(
        "produtos.html",
        produtos=banco.listar_produtos(),
        modelos=banco.listar_valores_distintos("modelo"),
        cores=banco.listar_valores_distintos("cor_produto"),
        formulario=formulario,
    )


@app.route("/rolos", methods=["GET", "POST"])
def rolos():
    formulario = {}
    if request.method == "POST":
        formulario = request.form
        try:
            codigo = banco.cadastrar_rolo(
                tipo_tecido=formulario.get("tipo_tecido", ""),
                cor=formulario.get("cor", ""),
                metragem=formulario.get("metragem", ""),
            )
        except banco.ErroEstoque as erro:
            flash(str(erro), "erro")
        else:
            flash(f"Rolo cadastrado com o código {codigo}. Imprima a etiqueta e cole no rolo.", "sucesso")
            return redirect(url_for("etiqueta", codigo=codigo))

    return render_template(
        "rolos.html",
        rolos=banco.listar_rolos(),
        tipos=banco.listar_valores_distintos("tipo_tecido"),
        cores=banco.listar_valores_distintos("cor_rolo"),
        formulario=formulario,
    )


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


@app.route("/etiqueta/<codigo>")
def etiqueta(codigo):
    item = banco.buscar_item(codigo)
    if item is None:
        abort(404)
    # Quantas etiquetas iguais imprimir (entre 1 e 100)
    copias = request.args.get("copias", 1, type=int)
    copias = max(1, min(copias, 100))
    return render_template("etiqueta.html", item=item, copias=copias)


@app.route("/codigo-barras/<codigo>.png")
def imagem_codigo_barras(codigo):
    """Devolve a IMAGEM do código de barras. É usada no <img> da etiqueta."""
    try:
        codigo = banco.limpar_codigo(codigo)
    except banco.ErroEstoque:
        abort(404)
    return Response(gerar_png_codigo_barras(codigo), mimetype="image/png")


# =====================================================================
# API (JSON) — usada pelo JavaScript, sem recarregar a página
# =====================================================================

@app.route("/api/item/<codigo>")
def api_item(codigo):
    """Diz o que é o código bipado (pijama ou rolo) e o saldo atual."""
    item = banco.buscar_item(codigo)
    if item is None:
        return jsonify(ok=False, erro=f"Código {codigo.upper()} não encontrado."), 404
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
        produtos=banco.listar_produtos(),
        rolos=banco.listar_rolos(somente_com_saldo=True),
        movimentacoes=banco.listar_movimentacoes(limite=15),
        limites={"pijamas": banco.LIMITE_PIJAMAS_BAIXO, "metros": banco.LIMITE_METROS_BAIXO},
    )


if __name__ == "__main__":
    # host="0.0.0.0": aceita conexões de OUTROS computadores da rede, não só deste.
    # debug=False: o modo debug permite rodar código pelo navegador, então NUNCA
    # deve ficar ligado com o sistema aberto para a rede.
    app.run(host="0.0.0.0", port=5000, debug=False)
