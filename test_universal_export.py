import pytest

from universal_export import montar_resultado_controlado, gerar_xlsx_universal_controlado


def _preview(aprovado=True):
    return {
        "url_final":"https://exemplo.com/menu",
        "validacao":{"aprovado":aprovado},
        "produtos":[
            {"codigo":"1","nome":"Burger","preco":25,"categoria":"Lanches","imagem":"","grupos":["g1"],"pizza":False,"metodo_preco_pizza":0},
            {"codigo":"2","nome":"Pizza G","preco":40,"categoria":"Pizzas","imagem":"","grupos":["g2"],"pizza":True,"metodo_preco_pizza":3},
        ],
        "grupos":[
            {"grupo_id":"g1","tipo":1,"grupo_nome":"Adicionais","nome":"Bacon","preco":4,"minimo":0,"maximo":2,"repetir":0,"metodo_preco":1},
            {"grupo_id":"g2","tipo":2,"grupo_nome":"Sabores","nome":"Calabresa","preco":40,"minimo":1,"maximo":2,"repetir":0,"metodo_preco":1},
        ],
        "avisos":[],
    }


def test_adapter_separa_itens_e_pizzas():
    r=montar_resultado_controlado(_preview(True))
    assert len(r.itens) == 1
    assert len(r.pizzas) == 1
    assert len(r.grupos) == 2


def test_adapter_bloqueia_previa_reprovada():
    with pytest.raises(ValueError):
        montar_resultado_controlado(_preview(False))


def test_exportacao_exige_confirmacao_antes_de_tocar_template():
    with pytest.raises(PermissionError):
        gerar_xlsx_universal_controlado(b"nao-importa", _preview(True), confirmar=False)


def test_pizza_sem_metodo_e_bloqueada():
    p=_preview(True)
    p["produtos"][1]["metodo_preco_pizza"] = 0
    with pytest.raises(ValueError):
        montar_resultado_controlado(p)
