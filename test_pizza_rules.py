from pizza_rules import diagnosticar_pizza
from utils import parece_pizza


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


def test_meia_isolada_nao_classifica_produto_comum_como_pizza():
    assert parece_pizza("Produto meia unidade", "Bebidas", "") is False


def test_fracao_isolada_nao_classifica_produto_comum_como_pizza():
    assert parece_pizza("Produto 1/2 unidade", "Outros", "") is False


def test_meia_com_contexto_tipico_de_pizza_continua_sendo_detectada():
    assert parece_pizza("Meia Calabresa", "", "Escolha os sabores") is True


def test_categoria_pizzas_continua_sendo_evidencia_direta():
    assert parece_pizza("Calabresa", "Pizzas", "") is True
