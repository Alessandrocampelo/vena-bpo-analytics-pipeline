"""Extração das tabelas do banco transacional (SQLite).

`clientes` e `produtos` são pequenos (~6.180 e ~800 linhas — ver
docs/01-descoberta.md) e cabem em memória inteiros. `itens_pedido` tem
5.000.000 de linhas e nunca é carregado de uma vez (ADR-002): lido em
chunks via cursor.fetchmany(), nunca fetchall() nem pandas.read_sql sem
chunksize.
"""

import sqlite3
from collections.abc import Iterator

from ingestion.config import Config


def _connect(config: Config) -> sqlite3.Connection:
    conn = sqlite3.connect(config.sqlite_db_path)
    conn.row_factory = sqlite3.Row
    return conn


def extract_clientes(config: Config) -> list[dict]:
    conn = _connect(config)
    try:
        rows = conn.execute("SELECT * FROM clientes").fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def extract_produtos(config: Config) -> list[dict]:
    conn = _connect(config)
    try:
        rows = conn.execute("SELECT * FROM produtos").fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def extract_itens_pedido_chunks(
    config: Config, chunk_size: int | None = None
) -> Iterator[list[dict]]:
    """Generator: cada iteração devolve até chunk_size linhas de itens_pedido.

    Nunca materializa a tabela inteira em memória — cada chunk é
    descartado pelo chamador antes do próximo ser lido.
    """
    chunk_size = chunk_size or config.sqlite_chunk_size
    conn = _connect(config)
    try:
        cursor = conn.execute("SELECT * FROM itens_pedido")
        while True:
            rows = cursor.fetchmany(chunk_size)
            if not rows:
                break
            yield [dict(row) for row in rows]
    finally:
        conn.close()
