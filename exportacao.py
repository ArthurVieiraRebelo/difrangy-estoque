"""
exportacao.py
-------------
Gera arquivos CSV (planilha) a partir dos dados do sistema.

Detalhes para o Excel em português abrir certo:
- separador ";" (o Excel brasileiro usa a vírgula como separador decimal);
- números com vírgula decimal: 12,50;
- o arquivo começa com o caractere invisível "BOM" (\\ufeff), que avisa
  ao Excel que o texto está em UTF-8. Sem ele, "Algodão" vira "AlgodÃ£o".
"""

import csv
import io

import banco


def _texto_seguro(valor):
    """Protege contra "fórmulas escondidas".

    O Excel trata como FÓRMULA qualquer célula que começa com = + - ou @.
    Se alguém cadastrasse um modelo chamado "=HIPERLINK(...)", ao abrir o
    CSV o Excel executaria aquilo. Um apóstrofo na frente faz o Excel
    mostrar o texto como texto.
    """
    texto = "" if valor is None else str(valor)
    if texto[:1] in ("=", "+", "-", "@"):
        return "'" + texto
    return texto


def _numero(valor, casas=0):
    """12.5 -> '12,50' (casas=2)."""
    return f"{float(valor):.{casas}f}".replace(".", ",")


def _gerar_csv(cabecalho, linhas):
    buffer = io.StringIO()  # um "arquivo" de texto na memória
    escritor = csv.writer(buffer, delimiter=";")
    escritor.writerow(cabecalho)
    escritor.writerows(linhas)
    return "﻿" + buffer.getvalue()


def csv_pijamas(produtos):
    return _gerar_csv(
        ["Código", "Modelo", "Tamanho", "Cor", "Quantidade", "Estoque baixo com até", "Situação"],
        [[_texto_seguro(p["codigo"]), _texto_seguro(p["modelo"]), _texto_seguro(p["tamanho"]),
          _texto_seguro(p["cor"]), p["quantidade"], p["limite_baixo"],
          "Ativo" if p["ativo"] else "Desativado"]
         for p in produtos],
    )


def csv_rolos(rolos):
    return _gerar_csv(
        ["Código", "Tecido", "Cor", "Metros", "Situação"],
        [[_texto_seguro(r["codigo"]), _texto_seguro(r["tipo_tecido"]), _texto_seguro(r["cor"]),
          _numero(r["metragem_atual"], 2), "Ativo" if r["ativo"] else "Desativado"]
         for r in rolos],
    )


def csv_movimentacoes(movimentacoes):
    linhas = []
    for m in movimentacoes:
        casas = 2 if m["tipo_item"] == "rolo" else 0
        linhas.append([
            m["data"],
            _texto_seguro(m["codigo_item"]),
            _texto_seguro(m["descricao"]),
            "Entrada" if m["tipo"] == "entrada" else "Saída",
            _numero(m["quantidade"], casas),
            "m" if m["tipo_item"] == "rolo" else "un.",
            banco.MOTIVOS.get(m["motivo"], m["motivo"]),
            _texto_seguro(m["usuario"]),
        ])
    return _gerar_csv(
        ["Data/hora", "Código", "Item", "Operação", "Quantidade", "Unidade", "Motivo", "Usuário"],
        linhas,
    )


def csv_consumo_tecido(consumo):
    return _gerar_csv(
        ["Mês", "Tecido", "Cor", "Metros cortados"],
        [[c["mes"], _texto_seguro(c["tipo_tecido"]), _texto_seguro(c["cor"]), _numero(c["metros"], 2)]
         for c in consumo],
    )


def csv_vendas(vendas):
    return _gerar_csv(
        ["Mês", "Modelo", "Unidades vendidas"],
        [[v["mes"], _texto_seguro(v["modelo"]), v["unidades"]] for v in vendas],
    )
