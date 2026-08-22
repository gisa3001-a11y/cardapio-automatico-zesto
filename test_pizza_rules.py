from pizza_rules import diagnosticar_pizza


def test_pizza_com_sabores_precos_diferentes_sugere_maior_valor():
    produto = {
        "codigo": "P1",
        "nome": "Pizza Grande",
        "categoria": "Pizzas",
        "grupos": ["G-SABOR", "G-BORDA"],
    }
    grupos = [
        {"grupo_id": "G-SABOR", "grupo_nome": "Escolha os sabores", "tipo": 2, "nome": "Calabresa", "preco": 35.0},
        {"grupo_id": "G-SABOR", "grupo_nome": "Escolha os sabores", "tipo": 2, "nome": "Portuguesa", "preco": 40.0},
        {"grupo_id": "G-BORDA", "grupo_nome": "Borda", "tipo": 3, "nome": "Catupiry", "preco": 5.0},
    ]
    d = diagnosticar_pizza(produto, grupos)
    assert d.pizza is True
    assert d.metodo_preco_pizza == 3
    assert d.confianca == "alta"


def test_pizza_sem_evidencia_de_preco_fica_indefinida():
    produto = {
        "codigo": "P2",
        "nome": "Pizza Familia",
        "categoria": "Pizzas",
        "grupos": ["G-SABOR"],
    }
    grupos = [
        {"grupo_id": "G-SABOR", "grupo_nome": "Sabores", "tipo": 2, "nome": "Mussarela", "preco": 0.0},
        {"grupo_id": "G-SABOR", "grupo_nome": "Sabores", "tipo": 2, "nome": "Frango", "preco": 0.0},
    ]
    d = diagnosticar_pizza(produto, grupos)
    assert d.pizza is True
    assert d.metodo_preco_pizza == 0


def test_produto_com_sabor_sem_contexto_nao_vira_pizza_automaticamente():
    produto = {
        "codigo": "P3",
        "nome": "Milk Shake",
        "categoria": "Bebidas",
        "grupos": ["G-SABOR"],
    }
    grupos = [
        {"grupo_id": "G-SABOR", "grupo_nome": "Escolha o sabor", "tipo": 2, "nome": "Morango", "preco": 0.0},
    ]
    d = diagnosticar_pizza(produto, grupos)
    assert d.pizza is False
