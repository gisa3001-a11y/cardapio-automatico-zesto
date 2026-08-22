"""Testes simples da camada de filtro da previa generica V2.

Nao acessa internet e nao mexe no app oficial.
Executar manualmente com: python test_generic_preview_filters.py
"""
from generic_preview import gerar_previa_de_payload


def nomes(previa):
    return {p.nome for p in previa.produtos}


def test_filtra_taxas_e_carrinho():
    payload = {
        "products": [
            {"id": 1, "name": "X-Burger", "price": 25.90, "image": "https://img/x.jpg", "category": "Lanches"},
            {"id": 2, "name": "Batata Frita", "price": 14.00, "category": "Porcoes"},
        ],
        "cart": {"name": "Carrinho", "price": 39.90},
        "delivery_fee": {"name": "Taxa de entrega", "price": 6.00},
        "checkout": {"name": "Total", "price": 45.90},
    }
    previa = gerar_previa_de_payload(payload)
    assert "X-Burger" in nomes(previa)
    assert "Batata Frita" in nomes(previa)
    assert "Carrinho" not in nomes(previa)
    assert "Taxa de entrega" not in nomes(previa)
    assert "Total" not in nomes(previa)


def test_remove_duplicado_com_ids_diferentes():
    payload = {
        "items": [
            {"id": "a", "name": "Coca-Cola 350ml", "price": 7.0, "image": "https://img/coca.jpg"},
            {"id": "b", "name": "Coca-Cola 350ml", "price": 7.0, "image": "https://img/coca.jpg"},
        ]
    }
    previa = gerar_previa_de_payload(payload)
    assert len(previa.produtos) == 1
    assert previa.descartados_duplicados >= 1


def test_nao_confia_em_metadados():
    payload = {
        "store": {"name": "Minha Loja", "price": 0},
        "address": {"name": "Rua A", "price": 0},
        "settings": {"name": "Pedido minimo", "price": 20},
    }
    previa = gerar_previa_de_payload(payload)
    assert len(previa.produtos) == 0
    assert previa.confianca == "baixa"


if __name__ == "__main__":
    test_filtra_taxas_e_carrinho()
    test_remove_duplicado_com_ids_diferentes()
    test_nao_confia_em_metadados()
    print("OK - filtros da previa universal passaram")
