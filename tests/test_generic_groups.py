from generic_preview import gerar_previa_de_payload


def test_extrai_grupo_adicionais_com_min_max():
    payload = {
        "products": [
            {
                "id": "p1",
                "name": "X-Burger",
                "price": 25.0,
                "category": "Lanches",
                "options": [
                    {
                        "id": "g1",
                        "name": "Adicionais",
                        "min": 0,
                        "max": 2,
                        "items": [
                            {"id": "a1", "name": "Bacon", "price": 4.0},
                            {"id": "a2", "name": "Queijo", "price": 3.5},
                        ],
                    }
                ],
            }
        ]
    }
    previa = gerar_previa_de_payload(payload)
    assert len(previa.produtos) == 1
    assert previa.produtos[0].grupos == ["g1"]
    assert len(previa.grupos) == 2
    assert {g.nome for g in previa.grupos} == {"Bacon", "Queijo"}
    assert all(g.minimo == 0 and g.maximo == 2 for g in previa.grupos)


def test_classifica_sabor_e_borda():
    payload = {
        "products": [
            {
                "name": "Pizza Grande",
                "price": 50.0,
                "option_groups": [
                    {
                        "name": "Sabores",
                        "minimum": 1,
                        "maximum": 2,
                        "options": [
                            {"name": "Calabresa", "price": 0},
                            {"name": "Frango", "price": 2},
                        ],
                    },
                    {
                        "name": "Borda",
                        "min": 0,
                        "max": 1,
                        "options": [{"name": "Catupiry", "price": 8}],
                    },
                ],
            }
        ]
    }
    previa = gerar_previa_de_payload(payload)
    tipos = {(g.grupo_nome, g.tipo) for g in previa.grupos}
    assert ("Sabores", 2) in tipos
    assert ("Borda", 3) in tipos


def test_nao_cria_grupo_sem_opcoes():
    payload = {
        "products": [
            {
                "name": "Suco",
                "price": 9.0,
                "extras": [{"name": "Observacao", "max": 1}],
            }
        ]
    }
    previa = gerar_previa_de_payload(payload)
    assert len(previa.produtos) == 1
    assert previa.produtos[0].grupos == []
    assert previa.grupos == []
