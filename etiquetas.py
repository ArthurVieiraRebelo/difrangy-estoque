"""
etiquetas.py
------------
Gera a imagem PNG do código de barras (formato Code128).

A imagem é gerada na MEMÓRIA (BytesIO) e enviada direto para o navegador,
em vez de salvar um arquivo .png para cada item. Assim não acumulam arquivos
na pasta, e a etiqueta sempre sai igual ao código que está no banco.
"""

from io import BytesIO

from barcode import Code128
from barcode.writer import ImageWriter

# Ajustes de aparência (medidas em milímetros, exceto font_size e dpi)
OPCOES = {
    "module_width": 0.3,    # largura da barra mais fina
    "module_height": 12.0,  # altura das barras
    "quiet_zone": 3.0,      # margem branca nas laterais (o leitor precisa dela)
    "font_size": 9,         # tamanho do texto embaixo das barras
    "text_distance": 4.0,   # distância entre as barras e o texto
    "dpi": 300,             # resolução boa para impressão
}


def gerar_png_codigo_barras(codigo):
    """Recebe o texto do código (ex: 'PJ-FLO-M-AZ') e devolve os bytes da imagem PNG."""
    buffer = BytesIO()  # funciona como um arquivo, mas fica na memória
    Code128(codigo, writer=ImageWriter()).write(buffer, options=OPCOES)
    return buffer.getvalue()
