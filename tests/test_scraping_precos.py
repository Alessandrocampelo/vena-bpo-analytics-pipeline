"""Testes do parser de scraping — usa fixtures HTML reais capturadas do serviço
(tests/fixtures/scraping_layout_{a,b,c}.html), nenhuma chamada de rede."""

from pathlib import Path

import pytest

from ingestion.scraping_precos import parse_html, _split_produto_categoria

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> str:
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "fixture,expected_strategy",
    [
        ("scraping_layout_a.html", "A"),
        ("scraping_layout_b.html", "B"),
        ("scraping_layout_c.html", "C"),
    ],
)
def test_parse_html_reconhece_cada_layout_real(fixture, expected_strategy):
    html = load_fixture(fixture)
    records, strategy = parse_html(html)

    assert strategy == expected_strategy
    assert len(records) == 12  # os 3 fixtures reais têm 12 linhas cada
    primeiro = records[0]
    assert primeiro["produto_nome"] == "Tênis Runner Pro"
    assert primeiro["categoria"] == "Calçados"
    assert primeiro["concorrente"] == "ConcorrenteA"
    assert isinstance(primeiro["preco"], float)
    assert primeiro["disponibilidade"] in {"Indisponível", "Últimas unidades", "Em estoque"}


def test_parse_html_layout_c_separa_produto_com_parenteses_no_proprio_nome():
    """Caso real: 'Meia Performance (3un)' já tem parênteses — não pode confundir
    com o parêntese que separa a categoria no final ('... (Acessórios)')."""
    html = load_fixture("scraping_layout_c.html")
    records, _ = parse_html(html)

    meia = next(r for r in records if r["produto_nome"].startswith("Meia Performance"))
    assert meia["produto_nome"] == "Meia Performance (3un)"
    assert meia["categoria"] == "Acessórios"


@pytest.mark.parametrize(
    "item,esperado",
    [
        ("Tênis Runner Pro (Calçados)", ("Tênis Runner Pro", "Calçados")),
        ("Meia Performance (3un) (Acessórios)", ("Meia Performance (3un)", "Acessórios")),
        ("Sem categoria nenhuma", ("Sem categoria nenhuma", None)),
    ],
)
def test_split_produto_categoria(item, esperado):
    assert _split_produto_categoria(item) == esperado


def test_parse_html_layout_desconhecido_cai_no_fallback_sem_quebrar():
    html_desconhecido = """
    <html><body>
        <div>Tênis X - Loja Y - R$ 199.90 - Em estoque</div>
    </body></html>
    """
    records, strategy = parse_html(html_desconhecido)
    # fallback pode ou não conseguir extrair algo — o que importa é não lançar exceção
    assert strategy in {"fallback", "nenhuma"}
    assert isinstance(records, list)


def test_parse_html_html_vazio_retorna_vazio_sem_quebrar():
    records, strategy = parse_html("<html><body></body></html>")
    assert records == []
    assert strategy == "nenhuma"


def test_force_unknown_layout_simula_falha_total_mesmo_com_html_valido():
    """Prova que a flag de demo força falha mesmo quando o HTML real é reconhecível."""
    html_valido = load_fixture("scraping_layout_a.html")
    records, strategy = parse_html(html_valido, force_unknown_layout=True)
    assert records == []
    assert strategy == "nenhuma"
