"""
etiquetas.py
------------
Gera as imagens PNG das etiquetas: código de barras (Code128) e QR code.

Os dois guardam o MESMO texto (o código do item, ex: PJ-FLO-M-AZ). Assim,
qualquer um dos dois funciona na tela Bipar — desde que o leitor consiga ler
aquele tipo. Leitores "laser" comuns só leem código de barras; para QR code
é preciso um leitor de imagem (chamado de leitor 2D).

A imagem é gerada na MEMÓRIA (BytesIO) e enviada direto para o navegador,
em vez de salvar um arquivo .png para cada item. Assim não acumulam arquivos
na pasta, e a etiqueta sempre sai igual ao código que está no banco.
"""

from io import BytesIO

import qrcode
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


def gerar_png_qrcode(codigo):
    """Recebe o texto do código e devolve os bytes da imagem PNG do QR code.

    error_correction M: o QR continua legível mesmo com ~15% dele danificado
                        (ex: etiqueta amassada ou um pouco suja).
    border=4: margem branca de 4 "quadradinhos", o mínimo que a norma do QR pede.
    """
    gerador = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,  # cada quadradinho com 10 pixels: imagem nítida na impressão
        border=4,
    )
    gerador.add_data(codigo)
    gerador.make(fit=True)  # fit=True: escolhe sozinho o menor tamanho de QR que cabe o texto
    imagem = gerador.make_image(fill_color="black", back_color="white")

    buffer = BytesIO()
    imagem.save(buffer, format="PNG")
    return buffer.getvalue()
