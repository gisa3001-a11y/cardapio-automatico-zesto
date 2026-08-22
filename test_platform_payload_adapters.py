from platform_payload_adapters import adaptar_payload
from generic_preview import gerar_previa_de_payload


def test_adaptador_neemo_converte_produto_e_adicionais():
    payload = {
        "data": {
            "categories": [
                {
                    "id": "c1", "title": "Lanches", "enabled": True,
                    "items": [
                        {
                            "id": "p1", "title": "X-Burger", "description": "Carne e queijo",
                            "enabled": True, "show_on_menu": True,
                            "image": {"original": "https://img.exemplo/x.jpg"},
                            "prices": [{"enabled": True, "value": 25.9}],
                            "complement_categories": [
                                {
                                    "id": "g1", "title": "Adicionais", "enabled": True,
                                    "minimum_choice": 0, "maximum_choice": 2,
                                    "choose_more_than_one": True,
                                    "complements": [
                                        {"id": "a1", "title": "Bacon", "enabled": True, "price": 4.0}
                                    ],
                                }
                            ],
                        }
                    ],
                }
            ]
        }
    }
    adaptado, nome = adaptar_payload(
        "browser:https://ecommerce-api.prod.neemo.com.br/api/ecommerce/v1/merchants/x/menu",
        payload,
    )
    assert nome == "adaptador-neemo"
    previa = gerar_previa_de_payload(adaptado)
    assert len(previa.produtos) == 1
    assert previa.produtos[0].nome == "X-Burger"
    assert previa.produtos[0].preco == 25.9
    assert previa.produtos[0].grupos == ["g1"]
    assert len(previa.grupos) == 1
    assert previa.grupos[0].nome == "Bacon"
    assert previa.grupos[0].preco == 4.0


def test_adaptador_neemo_ignora_item_oculto():
    payload = {"data": {"categories": [{"title": "X", "enabled": True, "items": [
        {"id": "1", "title": "Oculto", "enabled": True, "show_on_menu": False, "prices": [{"value": 10}]}
    ]}]}}
    adaptado, _ = adaptar_payload(
        "browser:https://ecommerce-api.prod.neemo.com.br/api/ecommerce/v1/merchants/x/menu",
        payload,
    )
    assert adaptado is payload or adaptado.get("products") == []
