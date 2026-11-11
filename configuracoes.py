"""
configuracoes.py
----------------
Configurações do sistema que o MASTER liga e desliga pela tela de
Administração (hoje: quais tipos de etiqueta podem ser gerados).

Ficam na tabela "configuracoes" como pares chave/valor. Uma chave que
nunca foi salva usa o valor de PADROES.
"""

import banco

# Tipos de etiqueta: chave da configuração, nome (títulos) e texto do botão
TIPOS_ETIQUETA = {
    "barras": {"chave": "etiqueta_barras", "nome": "Código de barras", "botao": "Gerar código de barras"},
    "qr": {"chave": "etiqueta_qr", "nome": "QR code", "botao": "Gerar QR code"},
}

# Valor de cada configuração enquanto ninguém mudou ("1" = ligado)
PADROES = {
    "etiqueta_barras": "1",
    "etiqueta_qr": "1",
}


def obter(chave):
    linha = banco.consultar_um("SELECT valor FROM configuracoes WHERE chave = ?", (chave,))
    return linha["valor"] if linha else PADROES[chave]


def definir(chave, valor):
    """Salva uma configuração.

    "INSERT ... ON CONFLICT DO UPDATE" (chamado de UPSERT) insere a linha se a
    chave ainda não existe, ou atualiza o valor se ela já existe — num comando só.
    """
    if chave not in PADROES:
        raise ValueError(f"Configuração desconhecida: {chave}")
    banco.executar(
        """INSERT INTO configuracoes (chave, valor) VALUES (?, ?)
           ON CONFLICT (chave) DO UPDATE SET valor = excluded.valor""",
        (chave, str(valor)),
    )


def etiqueta_liberada(tipo):
    """True se o master deixou este tipo de etiqueta ("barras" ou "qr") ligado."""
    return tipo in TIPOS_ETIQUETA and obter(TIPOS_ETIQUETA[tipo]["chave"]) == "1"


def tipos_de_etiqueta_liberados():
    """Lista dos tipos ligados com o texto do botão,
    ex: [("barras", "Gerar código de barras"), ("qr", "Gerar QR code")].
    Usada para decidir quais botões aparecem nas listas."""
    return [(tipo, dados["botao"]) for tipo, dados in TIPOS_ETIQUETA.items() if etiqueta_liberada(tipo)]
