from price_resolution import aplicar_resolucao_precos
from universal_validation import validar_previa


def test_preco_zero_resolvido_por_tamanho():
    produtos=[{"codigo":"1","nome":"Acai","preco":0,"grupos":["g1"],"imagem":"https://img/x.jpg","categoria":"Acai"}]
    grupos=[
        {"grupo_id":"g1","grupo_nome":"Escolha o tamanho","nome":"300ml","preco":12,"minimo":1,"maximo":1},
        {"grupo_id":"g1","grupo_nome":"Escolha o tamanho","nome":"500ml","preco":18,"minimo":1,"maximo":1},
    ]
    saida, diags=aplicar_resolucao_precos(produtos,grupos)
    assert saida[0]["preco"] == 12
    assert diags[0]["resolvido"] is True
    assert diags[0]["confianca"] == "alta"


def test_preco_zero_nao_inventa_com_grupos_divergentes():
    produtos=[{"codigo":"1","nome":"Produto","preco":0,"grupos":["g1","g2"]}]
    grupos=[
        {"grupo_id":"g1","grupo_nome":"Tamanho","nome":"P","preco":10,"minimo":1,"maximo":1},
        {"grupo_id":"g2","grupo_nome":"Volume","nome":"300ml","preco":12,"minimo":1,"maximo":1},
    ]
    saida, diags=aplicar_resolucao_precos(produtos,grupos)
    assert saida[0]["preco"] == 0
    assert diags[0]["resolvido"] is False


def test_validacao_bloqueia_pizza_indefinida():
    produtos=[]
    for i in range(10):
        produtos.append({
            "codigo":str(i),"nome":f"Pizza {i}","preco":30+i,"grupos":["g1"],
            "imagem":f"https://img/{i}.jpg","categoria":"Pizzas"
        })
    grupos=[{"grupo_id":"g1","grupo_nome":"Sabores","nome":"Mussarela","preco":30,"minimo":1,"maximo":2}]
    pizzas=[{"codigo":"0","nome":"Pizza 0","pizza":True,"metodo_preco_pizza":0}]
    v=validar_previa(produtos,grupos,pizzas,"alta")
    assert v.aprovado is False
    assert any("metodo de preco" in e for e in v.erros)


def test_validacao_aprova_estrutura_coerente():
    produtos=[]
    for i in range(10):
        produtos.append({
            "codigo":str(i),"nome":f"Item {i}","preco":20+i,"grupos":["g1"],
            "imagem":f"https://img/{i}.jpg","categoria":"Lanches"
        })
    grupos=[{"grupo_id":"g1","grupo_nome":"Adicionais","nome":"Bacon","preco":4,"minimo":0,"maximo":3}]
    v=validar_previa(produtos,grupos,[],"alta")
    assert v.aprovado is True
    assert v.score >= 85
