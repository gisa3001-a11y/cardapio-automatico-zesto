from pizza_rules import diagnosticar_pizza
from utils import parece_combo, parece_pizza


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


def test_oferta_de_duas_pizzas_e_combo_e_nao_pizza_unitaria():
    nome = "2 deliciosas pizzas grandes"
    descricao = "2 Pizzas Grandes de R$139,90 por apenas R$89,90"
    assert parece_combo(nome, descricao) is True
    assert parece_pizza(nome, "Promoções para Grupos", descricao) is False


def test_pizza_unitaria_continua_sendo_pizza():
    assert parece_combo("Grande - 8 Fatias", "8 Pedaços Escolha 1 ou 2 sabores") is False
    assert parece_pizza("Grande - 8 Fatias", "Pizzas Grandes", "8 Pedaços Escolha 1 ou 2 sabores") is True
