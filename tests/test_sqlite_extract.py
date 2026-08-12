"""Testes da extração do SQLite — banco temporário pequeno, nunca o arquivo real de 5M linhas."""

import sqlite3

import pytest

from ingestion.config import Config
from ingestion.sqlite_extract import (
    extract_clientes,
    extract_itens_pedido_chunks,
    extract_produtos,
)


def make_config(db_path: str) -> Config:
    return Config(
        api_base_url="unused",
        api_token="unused",
        sqlite_db_path=db_path,
        gcs_bucket_name="unused",
        bq_project_id="unused",
        bq_dataset="unused",
        api_max_concurrency=1,
        api_max_retries=1,
        sqlite_chunk_size=10,
    )


@pytest.fixture
def temp_db(tmp_path):
    """Banco SQLite temporário com o mesmo schema das 3 tabelas reais, populado com poucas linhas."""
    db_path = tmp_path / "banco_teste.sqlite"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE clientes (
            cliente_id INTEGER, nome TEXT, cpf TEXT, email TEXT,
            cidade TEXT, estado TEXT, data_cadastro TEXT, segmento TEXT
        );
        CREATE TABLE produtos (
            produto_id INTEGER, nome_produto TEXT, categoria TEXT,
            preco_tabela TEXT, ativo TEXT
        );
        CREATE TABLE itens_pedido (
            item_id INTEGER, pedido_id INTEGER, cliente_id INTEGER,
            produto_id INTEGER, data_item TEXT, quantidade INTEGER,
            valor_unitario REAL
        );
        """
    )
    conn.executemany(
        "INSERT INTO clientes VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (1, "Ana Silva", "111.111.111-11", "ana@example.com", "SP", "SP", "2024-01-01", "Varejo"),
            (2, "Bruno Costa", "222.222.222-22", None, "RJ", "RJ", "2024-02-01", None),
        ],
    )
    conn.executemany(
        "INSERT INTO produtos VALUES (?, ?, ?, ?, ?)",
        [
            (1, "Produto A", "Categoria X", "R$ 10.00", "1"),
            (2, "Produto B", "Categoria Y", "20.00", "0"),
        ],
    )
    # 25 linhas em itens_pedido -> com chunk_size=10, espera-se 3 chunks (10, 10, 5)
    conn.executemany(
        "INSERT INTO itens_pedido VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            (i, i, 1, 1, "2024-01-01 00:00:00", 1, 9.99)
            for i in range(1, 26)
        ],
    )
    conn.commit()
    conn.close()
    return str(db_path)


def test_extract_clientes(temp_db):
    clientes = extract_clientes(make_config(temp_db))
    assert len(clientes) == 2
    assert clientes[0]["nome"] == "Ana Silva"
    assert clientes[1]["email"] is None


def test_extract_produtos(temp_db):
    produtos = extract_produtos(make_config(temp_db))
    assert len(produtos) == 2
    assert produtos[0]["preco_tabela"] == "R$ 10.00"


def test_extract_itens_pedido_chunks_nao_perde_nem_duplica_linhas(temp_db):
    config = make_config(temp_db)
    chunks = list(extract_itens_pedido_chunks(config, chunk_size=10))

    assert len(chunks) == 3
    assert [len(c) for c in chunks] == [10, 10, 5]
    assert all(len(c) <= 10 for c in chunks)  # nenhum chunk excede o tamanho configurado

    todos_os_ids = [row["item_id"] for chunk in chunks for row in chunk]
    assert sorted(todos_os_ids) == list(range(1, 26))  # todas as 25 linhas, sem duplicar


def test_extract_itens_pedido_chunks_usa_chunk_size_do_config_por_default(temp_db):
    config = make_config(temp_db)  # sqlite_chunk_size=10 no config de teste
    chunks = list(extract_itens_pedido_chunks(config))
    assert [len(c) for c in chunks] == [10, 10, 5]
