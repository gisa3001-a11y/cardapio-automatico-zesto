from brendi_result_enrichment import enriquecer_resultado_brendi_nuxt
from models import Produto, Resultado


def _nuxt_fixture():
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
    data[3] = "pizza"
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


def _assert_audit_counts(audit, vinculados, opcoes):
    assert audit["produtos_vinculados"] == vinculados
    assert audit["opcoes_materializadas"] == opcoes


def test_enriquece_apenas_produto_com_tamanho_exato():
    alvo = Produto(codigo="1", nome="Grande - 8 Fatias", categoria="Pizzas Grandes", preco=45.0)
    outro = Produto(codigo="2", nome="Bebida", categoria="Bebidas", preco=8.0)
    resultado = Resultado(itens=[alvo, outro], origem="Brendi")

    resultado, audit = enriquecer_resultado_brendi_nuxt(resultado, _nuxt_fixture())

    _assert_audit_counts(audit, 1, 1)
    assert alvo.pizza is True
    assert alvo.metodo_preco_pizza == 3
    assert alvo.grupos == ["brendi-pizza-cat-grande-grande-8-fatias"]
    assert outro.grupos == []
    assert len(resultado.grupos) == 1
    grupo = resultado.grupos[0]
    assert grupo.tipo == 2
    assert grupo.nome == "3 queijos"
    assert grupo.preco == 54.0
    assert grupo.minimo == 1
    assert grupo.maximo == 2
    assert grupo.metodo_preco == 3


def test_nao_associa_quando_nome_do_tamanho_nao_bate_exatamente():
    resultado = Resultado(itens=[Produto(codigo="1", nome="Pizza Grande", categoria="Pizzas")], origem="Brendi")
    resultado, audit = enriquecer_resultado_brendi_nuxt(resultado, _nuxt_fixture())
    _assert_audit_counts(audit, 0, 0)
    assert resultado.grupos == []
    assert resultado.itens[0].grupos == []


def test_nao_materializa_correspondencia_ambigua():
    resultado = Resultado(itens=[
        Produto(codigo="1", nome="Grande - 8 Fatias"),
        Produto(codigo="2", nome="Grande - 8 Fatias"),
    ], origem="Brendi")
    resultado, audit = enriquecer_resultado_brendi_nuxt(resultado, _nuxt_fixture())
    _assert_audit_counts(audit, 0, 0)
    assert resultado.grupos == []
