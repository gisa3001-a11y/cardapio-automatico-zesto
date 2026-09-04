from brendi_nuxt_parser import extrair_pizzas_brendi_nuxt


def test_extrai_categoria_tamanho_sabor_e_preco_por_slug():
    data = [None] * 30
    data[0] = {
        "id": 1,
        "name": 2,
        "mainCategory": 3,
        "productsPaths": [4],
        "calculateType": 5,
    }
    data[1] = "cat-grande"
    data[2] = "Pizzas Grandes"
    data[3] = "pizza"
    data[4] = "stores/x/pizza-flavors/fl1"
    data[5] = "max"

    data[6] = {
        "name": 7,
        "slug": 8,
        "slices": 9,
        "numOfFlavors": [10, 11],
    }
    data[7] = "Grande - 8 Fatias"
    data[8] = "grande-8-fatias"
    data[9] = 8
    data[10] = 1
    data[11] = 2

    data[12] = {
        "id": 13,
        "name": 14,
        "slug": 15,
        "active": 16,
        "categoryPath": 17,
        "prices": [18],
        "pdvCodes": [19],
        "picture": 20,
        "description": 21,
    }
    data[13] = "fl1"
    data[14] = "3 queijos"
    data[15] = "3-queijos"
    data[16] = True
    data[17] = "stores/x/pizza-categories/cat-grande"
    data[18] = {"price": 22, "slug": 8}
    data[19] = {"pdvCode": 13, "size": 8}
    data[20] = "public/stores/x/images/products/fl1.jpg"
    data[21] = "Mussarela, parmesão e Catupiry"
    data[22] = 5400

    out = extrair_pizzas_brendi_nuxt(data)

    assert len(out["categories"]) == 1
    assert out["categories"][0]["id"] == "cat-grande"
    assert out["categories"][0]["calculateType"] == "max"

    assert len(out["sizes"]) == 1
    assert out["sizes"][0]["slug"] == "grande-8-fatias"
    assert out["sizes"][0]["slices"] == 8
    assert out["sizes"][0]["numOfFlavors"] == [1, 2]

    assert len(out["flavors"]) == 1
    sabor = out["flavors"][0]
    assert sabor["name"] == "3 queijos"
    assert sabor["prices"] == [{"price": 5400, "slug": "grande-8-fatias"}]
    assert sabor["pdvCodes"] == [{"pdvCode": "fl1", "size": "grande-8-fatias"}]
    assert out["flavorsByCategory"]["cat-grande"][0]["id"] == "fl1"


def test_rejeita_formato_inesperado():
    try:
        extrair_pizzas_brendi_nuxt({"x": 1})
    except ValueError as exc:
        assert "__NUXT_DATA__" in str(exc)
    else:
        raise AssertionError("Era esperado ValueError")
