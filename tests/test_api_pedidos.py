"""Testes do cliente da API de vendas — tudo mockado, nenhuma chamada de rede real."""

import json
from urllib.parse import parse_qs, urlparse

import pytest
import responses

from ingestion.api_pedidos import (
    CircuitBreakerError,
    VendasApiClient,
    parse_valor_unitario,
)
from ingestion.config import Config

API_BASE_URL = "http://test-api.local"


def make_config(**overrides) -> Config:
    defaults = dict(
        api_base_url=API_BASE_URL,
        api_token="test-token",
        scraping_base_url="unused",
        sqlite_db_path="unused",
        gcs_bucket_name="unused",
        bq_project_id="unused",
        bq_dataset="unused",
        api_max_concurrency=3,
        api_max_retries=6,
        sqlite_chunk_size=1000,
        force_unknown_layout=False,
    )
    defaults.update(overrides)
    return Config(**defaults)


def page_payload(page: int, total_pages: int, valor_unitario=10.0) -> dict:
    return {
        "data": [
            {
                "cliente_id": 1,
                "data_pedido": "2025-01-01T00:00:00",
                "pedido_id": page,
                "produto_id": 1,
                "quantidade": 1,
                "status": "pago",
                "updated_at": "2025-01-01T00:00:00",
                "valor_unitario": valor_unitario,
            }
        ],
        "has_next": page < total_pages,
        "page": page,
        "page_size": 500,
        "total_pages": total_pages,
        "total_records": total_pages,
    }


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("593.57 BRL", 593.57),
        (593.57, 593.57),
        (10, 10.0),
        (None, None),
        ("sem numero aqui", None),
    ],
)
def test_parse_valor_unitario_defensivo(raw, expected):
    assert parse_valor_unitario(raw) == expected


@responses.activate
def test_fetch_page_recupera_de_429_com_retry():
    call_count = {"n": 0}

    def flaky_then_ok(request):
        call_count["n"] += 1
        if call_count["n"] <= 2:
            return (429, {}, "")
        return (200, {}, json.dumps(page_payload(1, total_pages=1, valor_unitario="593.57 BRL")))

    responses.add_callback(responses.GET, f"{API_BASE_URL}/api/pedidos", callback=flaky_then_ok)

    client = VendasApiClient(make_config())
    records, payload = client.fetch_page(1, page_size=500)

    assert call_count["n"] == 3  # 2 tentativas falharam (429) antes da 3ª dar certo
    assert payload["total_pages"] == 1
    assert records[0]["valor_unitario"] == 593.57  # parsing defensivo aplicado


@responses.activate
def test_fetch_all_aborta_com_circuit_breaker_quando_paginas_falham_em_sequencia():
    total_pages = 5
    failing_pages = {2, 3, 4, 5}  # todas as páginas restantes falham

    def handler(request):
        page = int(parse_qs(urlparse(request.url).query)["page"][0])
        if page in failing_pages:
            return (500, {}, "")
        return (200, {}, json.dumps(page_payload(page, total_pages)))

    responses.add_callback(responses.GET, f"{API_BASE_URL}/api/pedidos", callback=handler)

    # api_max_retries=1: uma única tentativa por página, sem esperar backoff — teste rápido.
    client = VendasApiClient(make_config(api_max_retries=1, api_max_concurrency=3))

    with pytest.raises(CircuitBreakerError):
        client.fetch_all(page_size=500)
