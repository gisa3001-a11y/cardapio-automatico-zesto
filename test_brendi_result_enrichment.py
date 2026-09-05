from brendi_result_enrichment import enriquecer_resultado_brendi_nuxt
from models import Produto, Resultado


def _nuxt_fixture(main_category="pizza"):
    data = [None] * 40
    data[0] = {
        "id": 1,
        "name": 2,
        "mainCategory": 3,
        "productsPaths": [4],
        "calculateType": 5,
        "sizes": [6],
    }
    data[1] = "cat-grande"
    data[2] = "Pizzas Grandes"
    data[3] = main_category
    data[4] = "stores/x/pizza-flavors/fl1"
    data[5] = "max"
    data[6] = {
        "name": 7,
        "slug": 8,
        "slices": 9,
        "numOfFlavors": [10, 11],
        "active": 12,
    }
    data[7] = "Grande - 8 Fatias"
    data[8] = "grande-8-fatias"
    data[9] = 8
    data[10] = 1
    data[11] = 2
    data[12] = True
    data[13] = {
        "id": 14,
        "name": 15,
        "slug": 16,
        "active": 12,
        "categoryPath": 17,
        "prices": [18],
        "picture": 19,
        "description": 20,
    }
    data[14] = "fl1"
    data[15] = "3 queijos"
    data[16] = "3-queijos"
    data[17] = "stores/x/pizza-categories/cat-grande"
    data[18] = {"price": 21, "slug": 8}
    data[19] = "public/stores/x/images/products/fl1.jpg"
    data[20] = "Mussarela, parmesão e Catupiry"
    data[21] = 5400
    return data


def _assert_audit_counts(audit, vinculados, opcoes, criados=None):
    assert audit["produtos_vinculados"] == vinculados
    assert audit["opcoes_materializadas"] == opcoes
    if criados is not None:
        assert audit["produtos_criados"] == criados


def test_enriquece_produto_com_tamanho_exato_sem_criar_duplicata():
    alvo = Produto(codigo="1", nome="Grande - 8 Fatias", categoria="Pizzas Grandes", preco=45.0)
    outro = Produto(codigo="2", nome="Bebida", categoria="Bebidas", preco=8.0)
    resultado = Resultado(itens=[alvo, outro], origem="Brendi")

    resultado, audit = enriquecer_resultado_brendi_nuxt(resultado, _nuxt_fixture())

    _assert_audit_counts(audit, 1, 1, 0)
    assert alvo.pizza is True
    assert alvo.metodo_preco_pizza == 3
    assert alvo.grupos == ["brendi-pizza-cat-grande-grande-8-fatias"]
    assert outro.grupos == []
    assert resultado.pizzas == []
    assert len(resultado.grupos) == 1
    grupo = resultado.grupos[0]
    assert grupo.tipo == 2
    assert grupo.nome == "3 queijos"
    assert grupo.preco == 54.0
    assert grupo.minimo == 1
    assert grupo.maximo == 2
    assert grupo.metodo_preco == 3


def test_materializa_tamanho_ausente_quando_categoria_pizza_e_precos_sao_explicitos():
    resultado = Resultado(itens=[Produto(codigo="1", nome="Pizza Grande", categoria="Combos")], origem="Brendi")
    resultado, audit = enriquecer_resultado_brendi_nuxt(resultado, _nuxt_fixture())

    _assert_audit_counts(audit, 1, 1, 1)
    assert resultado.itens[0].grupos == []
    assert len(resultado.pizzas) == 1
    pizza = resultado.pizzas[0]
    assert pizza.nome == "Grande - 8 Fatias"
    assert pizza.categoria == "Pizzas Grandes"
    assert pizza.preco == 0.0
    assert pizza.pizza is True
    assert pizza.metodo_preco_pizza == 3
    assert pizza.grupos == ["brendi-pizza-cat-grande-grande-8-fatias"]
    assert resultado.grupos[0].preco == 54.0


def test_nao_materializa_tamanho_ausente_sem_categoria_pizza_explicita():
    resultado = Resultado(itens=[Produto(codigo="1", nome="Combo Grande", categoria="Combos")], origem="Brendi")
    resultado, audit = enriquecer_resultado_brendi_nuxt(resultado, _nuxt_fixture(main_category="combo"))
    _assert_audit_counts(audit, 0, 0, 0)
    assert resultado.grupos == []
    assert resultado.pizzas == []


def test_nao_materializa_correspondencia_ambigua():
    resultado = Resultado(itens=[
        Produto(codigo="1", nome="Grande - 8 Fatias"),
        Produto(codigo="2", nome="Grande - 8 Fatias"),
    ], origem="Brendi")
    resultado, audit = enriquecer_resultado_brendi_nuxt(resultado, _nuxt_fixture())
    _assert_audit_counts(audit, 0, 0, 0)
    assert resultado.grupos == []
    assert resultado.pizzas == []
