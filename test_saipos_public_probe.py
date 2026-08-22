from saipos_public_probe import _converter_view_data, _primeiro_id_loja


def test_primeiro_id_loja_variantes():
    assert _primeiro_id_loja([{"id_store": 123}]) == "123"
    assert _primeiro_id_loja({"data": [{"id": "abc"}]}) == "abc"


def test_converter_view_data_produto_e_adicional():
    payload = {
        "choices": [
            {
                "id_store_choice": 10,
                "desc_store_choice": "Adicionais",
                "min_choices": 0,
                "max_choices": 2,
                "choice_items": [
                    {
                        "desc_store_choice_item": "Bacon",
                        "enabled": "Y",
                        "variations": [{"aditional_price": "3,50"}],
                    }
                ],
            }
        ],
        "items": [
            {
                "id_store_item": 1,
                "desc_store_item": "X-Burger",
                "detail": "Hamburguer artesanal",
                "img_path": "https://img.example/x.jpg",
                "category_item": {"enabled": "Y", "desc_store_category_item": "Lanches"},
                "variations": [{"enabled": "Y", "price": "25,90"}],
                "choices": [{"id_store_choice": 10}],
            }
        ],
    }
    out = _converter_view_data(payload)
    assert len(out["products"]) == 1
    p = out["products"][0]
    assert p["name"] == "X-Burger"
    assert p["price"] == 25.9
    assert p["category"] == "Lanches"
    assert p["option_groups"][0]["options"][0]["name"] == "Bacon"
    assert p["option_groups"][0]["options"][0]["price"] == 3.5
