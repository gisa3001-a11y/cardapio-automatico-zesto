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
    assert any("Pizza 0 [0]" in e for e in v.erros)
    assert v.metricas["pizzas_metodo_indefinido"] == 1
    assert v.metricas["pizzas_metodo_indefinido_itens"] == ["Pizza 0 [0]"]


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


def test_validacao_nao_trata_preco_base_zero_com_grupo_precificado_como_pendente():
    produtos=[]
    for i in range(10):
        produtos.append({
            "codigo":str(i),"nome":f"Item {i}","preco":0 if i < 3 else 20+i,
            "grupos":["g1"] if i < 3 else [],
            "imagem":f"https://img/{i}.jpg","categoria":"Acai"
        })
    grupos=[{"grupo_id":"g1","grupo_nome":"Tamanho","nome":"300ml","preco":12,"minimo":1,"maximo":1}]
    v=validar_previa(produtos,grupos,[],"alta")
    assert v.metricas["precos_zero"] == 3
    assert v.metricas["precos_zero_estruturados"] == 3
    assert v.metricas["precos_zero_pendentes"] == 0
    assert v.metricas["precos_zero_pendentes_itens"] == []
    assert not any("Muitos produtos" in e for e in v.erros)


def test_validacao_identifica_produto_com_preco_zero_pendente():
    produtos=[
        {
            "codigo":str(i),
            "nome":"Produto Zero" if i == 0 else f"Item {i}",
            "preco":0 if i == 0 else 20+i,
            "grupos":[],
            "imagem":f"https://img/{i}.jpg",
            "categoria":"Lanches",
        }
        for i in range(10)
    ]
    v=validar_previa(produtos,[],[],"alta")
    assert v.metricas["precos_zero_pendentes"] == 1
    assert v.metricas["precos_zero_pendentes_itens"] == ["Produto Zero [0]"]
    assert any("Produto Zero [0]" in a for a in v.avisos)


def test_parser_oficial_pode_validar_cardapio_legitimo_com_dois_itens():
    produtos=[
        {"codigo":"1","nome":"Item A","preco":10,"grupos":[],"imagem":"https://img/a.jpg","categoria":"Lanches"},
        {"codigo":"2","nome":"Item B","preco":12,"grupos":[],"imagem":"https://img/b.jpg","categoria":"Lanches"},
    ]
    v=validar_previa(produtos,[],[],"alta",min_produtos=2)
    assert v.aprovado is True
    assert v.score >= 85


def test_ausencia_de_fotos_gera_alerta_mas_nao_bloqueia_estrutura_coerente():
    produtos=[
        {"codigo":str(i),"nome":f"Item {i}","preco":20+i,"grupos":[],"imagem":"","categoria":"Lanches"}
        for i in range(10)
    ]
    v=validar_previa(produtos,[],[],"alta")
    assert v.aprovado is True
    assert v.score >= 85
    assert any("foto" in a.lower() or "imagem" in a.lower() for a in v.avisos)
