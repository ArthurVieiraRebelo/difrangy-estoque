"""
backup.py
---------
Cópias de segurança do banco de dados.

Todo o estoque mora num único arquivo (estoque.db). Se o HD estragar ou o
arquivo for apagado, perde-se tudo. Por isso o sistema faz sozinho uma cópia
por dia na pasta "backups" e guarda as últimas 30.

Dica: de vez em quando, copie a pasta "backups" para um pendrive ou para a
nuvem. Backup que fica no mesmo computador não protege contra HD queimado.
"""

import os
import re
import sqlite3
import threading
import time
from datetime import date, datetime
from pathlib import Path

import banco

PASTA_BACKUPS = Path(os.environ.get("ESTOQUE_BACKUPS", Path(__file__).parent / "backups"))
QUANTIDADE_A_MANTER = 30
INTERVALO_VERIFICACAO_SEGUNDOS = 3600  # de hora em hora confere se o backup do dia já foi feito

# Formato do nome dos arquivos: estoque_2026-11-10_143005.db
PADRAO_NOME = re.compile(r"^estoque_\d{4}-\d{2}-\d{2}_\d{6}\.db$")


def fazer_backup():
    """Copia o banco para a pasta de backups. Devolve o nome do arquivo criado.

    Usamos o backup() do próprio SQLite em vez de copiar o arquivo: ele faz
    uma cópia consistente mesmo se alguém estiver bipando naquele instante.
    """
    PASTA_BACKUPS.mkdir(parents=True, exist_ok=True)
    nome = f"estoque_{datetime.now():%Y-%m-%d_%H%M%S}.db"

    origem = banco.conectar()
    destino = sqlite3.connect(PASTA_BACKUPS / nome)
    try:
        origem.backup(destino)
    finally:
        destino.close()
        origem.close()

    _apagar_backups_antigos()
    return nome


def listar_backups():
    """Backups existentes, do mais novo para o mais antigo."""
    if not PASTA_BACKUPS.exists():
        return []
    arquivos = [a for a in PASTA_BACKUPS.iterdir() if PADRAO_NOME.match(a.name)]
    arquivos.sort(key=lambda arquivo: arquivo.name, reverse=True)  # o nome tem a data
    return [
        {"nome": a.name, "tamanho_kb": round(a.stat().st_size / 1024, 1)}
        for a in arquivos
    ]


def nome_de_backup_valido(nome):
    """Só aceita nomes no formato que nós mesmos criamos.
    Impede pedidos como '../app.py' para baixar outros arquivos do computador."""
    return bool(PADRAO_NOME.match(nome))


def _apagar_backups_antigos():
    for backup in listar_backups()[QUANTIDADE_A_MANTER:]:
        (PASTA_BACKUPS / backup["nome"]).unlink()


def _backup_de_hoje_existe():
    prefixo = f"estoque_{date.today():%Y-%m-%d}_"
    return any(b["nome"].startswith(prefixo) for b in listar_backups())


def iniciar_backup_automatico():
    """Liga uma "thread" (tarefa que roda em paralelo ao site) que, de hora em
    hora, confere se o backup do dia já foi feito e faz se não foi.

    daemon=True: a thread termina sozinha quando o sistema é fechado.
    """
    def verificar_para_sempre():
        while True:
            try:
                if not _backup_de_hoje_existe():
                    print(f"Backup automático criado: {fazer_backup()}")
            except Exception as erro:  # um erro no backup não pode derrubar o sistema
                print(f"ERRO no backup automático: {erro}")
            time.sleep(INTERVALO_VERIFICACAO_SEGUNDOS)

    threading.Thread(target=verificar_para_sempre, daemon=True).start()
