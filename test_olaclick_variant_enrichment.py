from models import Produto, Resultado
from olaclick_variant_enrichment import enriquecer_resultado_olaclick_variantes


def _raw(produtos):
    return {
        "pinia": {
            "productsCategories": {
                "productsCategories": [
                    {"name": "Bistrot", "visible": True, "products": produtos}
                ]
            }
        }
    }


def test_duas_variantes_nomeadas_viram_escolha_obrigatoria_sem_dobrar_preco():
    res = Resultado(itens=[Produto(codigo="p1", nome="Croque Madame", preco=55.0)])
    raw = _raw([
        {
            "id": "p1",
            "visible": True,
            "product_variants": [
                {"id": "v1", "name": "baguette", "price": 5500},
                {"id": "v2", "name": "Croissant", "price": 6000},
            ],
        }
    ])

    _, audit = enriquecer_resultado_olaclick_variantes(res, raw)

    assert audit["produtos_vinculados"] == 1
    assert audit["opcoes_materializadas"] == 2
    assert res.itens[0].preco == 55.0
    assert len(res.itens[0].grupos) == 1
    opcoes = [g for g in res.grupos if g.grupo_id == res.itens[0].grupos[0]]
    assert [(g.nome, g.preco, g.minimo, g.maximo) for g in opcoes] == [
        ("baguette", 0.0, 1, 1),
        ("Croissant", 5.0, 1, 1),
    ]


def test_variante_unica_sem_nome_permanece_apenas_como_preco_do_produto():
    res = Resultado(itens=[Produto(codigo="p2", nome="Sopa", preco=55.0)])
    raw = _raw([
        {
            "id": "p2",
            "visible": True,
            "product_variants": [{"id": "v1", "name": None, "price": 5500}],
        }
    ])

    _, audit = enriquecer_resultado_olaclick_variantes(res, raw)

    assert audit["produtos_vinculados"] == 0
    assert audit["opcoes_materializadas"] == 0
    assert res.itens[0].preco == 55.0
    assert res.itens[0].grupos == []
    assert res.grupos == []


def test_nao_vincula_por_nome_quando_codigo_nao_corresponde():
    res = Resultado(itens=[Produto(codigo="outro", nome="Croque Madame", preco=55.0)])
    raw = _raw([
        {
            "id": "p1",
            "visible": True,
            "name": "Croque Madame",
            "product_variants": [
                {"name": "baguette", "price": 5500},
                {"name": "Croissant", "price": 5500},
            ],
        }
    ])

    _, audit = enriquecer_resultado_olaclick_variantes(res, raw)
    assert audit["produtos_vinculados"] == 0
    assert res.grupos == []
