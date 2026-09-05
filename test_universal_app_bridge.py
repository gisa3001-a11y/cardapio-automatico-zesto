from models import Produto, Resultado
import universal_app_bridge as bridge
from validator import validar


def test_mantem_fluxo_oficial_quando_ha_produtos(monkeypatch):
    esperado = Resultado(itens=[Produto(codigo="1", nome="Produto oficial", preco=10.0)])

    def buscar(url, usar_playwright=True):
        return esperado

    def nao_deveria_rodar(*args, **kwargs):
        raise AssertionError("fallback universal nao deveria ser chamado")

    monkeypatch.setattr(bridge, "gerar_previa_universal", nao_deveria_rodar)
    resultado, fonte = bridge.buscar_com_fallback_universal("https://exemplo.com", buscar)
    assert resultado is esperado
    assert fonte == "oficial"


def test_anota_move_vinho_falso_positivo_para_regular(monkeypatch):
    vinho = Produto(
        codigo="V1",
        nome="Vinho Villena 1L",
        categoria="Pizzas / Bebidas",
        preco=20.0,
        pizza=True,
        metodo_preco_pizza=0,
    )
    oficial = Resultado(pizzas=[vinho])

    def buscar(url, usar_playwright=True):
        return oficial

    resultado, fonte = bridge.buscar_com_fallback_universal(
        "https://app.anota.ai/m/teste", buscar
    )
    assert fonte == "oficial"
    assert resultado.pizzas == []
    assert resultado.itens == [vinho]
    assert vinho.pizza is False
    assert vinho.metodo_preco_pizza == 0
    assert getattr(resultado, "_leitor_universal", {}).get("plataforma") == "Anota AI"
    assert any("reclassificado" in aviso for aviso in resultado.avisos)

    erros, _ = validar(resultado)
    assert erros == []
    assert resultado.pizzas == []
    assert resultado.itens == [vinho]


def test_anota_nao_move_produto_que_realmente_menciona_pizza(monkeypatch):
    produto = Produto(
        codigo="P1",
        nome="Pizza com Vinho",
        categoria="Pizzas",
        preco=45.0,
        pizza=True,
        metodo_preco_pizza=3,
    )
    oficial = Resultado(pizzas=[produto])

    def buscar(url, usar_playwright=True):
        return oficial

    resultado, fonte = bridge.buscar_com_fallback_universal(
        "https://app.anota.ai/m/teste", buscar
    )
    assert fonte == "oficial"
    assert resultado.pizzas == [produto]
    assert resultado.itens == []
    assert produto.pizza is True
    assert produto.metodo_preco_pizza == 3


def test_usa_universal_somente_quando_oficial_zerar(monkeypatch):
    convertido = Resultado(itens=[Produto(codigo="U1", nome="Produto universal", preco=20.0)])
    previa = object()

    def buscar(url, usar_playwright=True):
        return Resultado()

    monkeypatch.setattr(bridge, "gerar_previa_universal", lambda *a, **k: previa)

    def converter(recebida, exigir_aprovacao=True):
        assert recebida is previa
        assert exigir_aprovacao is True
        return convertido

    monkeypatch.setattr(bridge, "converter_previa_para_resultado", converter)
    resultado, fonte = bridge.buscar_com_fallback_universal("https://exemplo.com", buscar)
    assert resultado is convertido
    assert fonte == "universal-v2"
    assert "Leitor Universal V2" in resultado.avisos[0]


def test_usa_universal_quando_oficial_lancar_erro(monkeypatch):
    convertido = Resultado(itens=[Produto(codigo="U2", nome="Recuperado", preco=15.0)])
    previa = object()

    def buscar(url, usar_playwright=True):
        raise RuntimeError("falha simulada")

    monkeypatch.setattr(bridge, "gerar_previa_universal", lambda *a, **k: previa)
    monkeypatch.setattr(
        bridge,
        "converter_previa_para_resultado",
        lambda p, exigir_aprovacao=True: convertido,
    )
    resultado, fonte = bridge.buscar_com_fallback_universal("https://exemplo.com", buscar)
    assert resultado is convertido
    assert fonte == "universal-v2"
    assert any("RuntimeError" in aviso for aviso in resultado.avisos)


def test_brendi_enriquece_resultado_oficial_quando_vinculo_foi_comprovado(monkeypatch):
    oficial = Resultado(itens=[Produto(codigo="1", nome="Combo", preco=50.0)])

    def buscar(url, usar_playwright=True):
        return oficial

    monkeypatch.setattr(bridge, "_enriquecer_brendi_url", lambda resultado, url: True)
    resultado, fonte = bridge.buscar_com_fallback_universal(
        "https://pedido.brendi.com.br/loja/", buscar
    )
    assert resultado is oficial
    assert fonte == "oficial+brendi-nuxt"
    assert any("Pizzas Brendi enriquecidas" in aviso for aviso in resultado.avisos)


def test_brendi_preserva_oficial_se_enriquecimento_falhar(monkeypatch):
    oficial = Resultado(itens=[Produto(codigo="1", nome="Combo", preco=50.0)])

    def buscar(url, usar_playwright=True):
        return oficial

    def falhar(*args, **kwargs):
        raise RuntimeError("mudanca simulada na fonte")

    monkeypatch.setattr(bridge, "_enriquecer_brendi_url", falhar)
    resultado, fonte = bridge.buscar_com_fallback_universal(
        "https://pedido.brendi.com.br/loja/", buscar
    )
    assert resultado is oficial
    assert fonte == "oficial"
    assert any("resultado oficial foi preservado" in aviso for aviso in resultado.avisos)
