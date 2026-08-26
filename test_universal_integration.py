from types import SimpleNamespace

import pytest

from universal_integration import converter_previa_para_resultado


def _previa(aprovado=True):
    return SimpleNamespace(
        fonte="browser:json [adaptador-teste]",
        produtos=[
            {"codigo":"1","nome":"Burger","descricao":"x","categoria":"Lanches","imagem":"https://img/b.jpg","preco":25,"grupos":["g1"]},
            {"codigo":"2","nome":"Pizza Grande","categoria":"Pizzas","preco":45,"grupos":["g2"],"pizza":True,"metodo_preco_pizza":3},
        ],
        grupos=[
            {"grupo_id":"g1","tipo":1,"grupo_nome":"Adicionais","nome":"Bacon","preco":4,"minimo":0,"maximo":2,"repetir":1,"metodo_preco":1},
            {"grupo_id":"g2","tipo":2,"grupo_nome":"Sabores","nome":"Mussarela","preco":0,"minimo":1,"maximo":2,"repetir":0,"metodo_preco":1},
        ],
        pizzas=[{"codigo":"2","pizza":True,"metodo_preco_pizza":3}],
        avisos=["aviso universal"],
        validacao={"aprovado":aprovado,"erros":[] if aprovado else ["pizza indefinida"],"avisos":["conferir fotos"]},
    )


def test_converte_para_modelos_existentes_sem_duplicar_pizza():
    r=converter_previa_para_resultado(_previa())
    assert len(r.itens) == 1
    assert len(r.pizzas) == 1
    assert len(r.grupos) == 2
    assert r.itens[0].grupos == ["g1"]
    assert r.pizzas[0].codigo == "2"
    assert r.pizzas[0].metodo_preco_pizza == 3
    assert r.grupos[0].grupo_id == "g1"
    assert "aviso universal" in r.avisos
    assert "conferir fotos" in r.avisos
    assert "Leitor Universal V2" in r.origem


def test_integracao_bloqueia_previa_reprovada_por_padrao():
    with pytest.raises(ValueError, match="pizza indefinida"):
        converter_previa_para_resultado(_previa(aprovado=False))


def test_integracao_pode_ser_forcada_apenas_para_diagnostico_controlado():
    r=converter_previa_para_resultado(_previa(aprovado=False), exigir_aprovacao=False)
    assert len(r.itens) + len(r.pizzas) == 2
