from rapidfood_public_probe import extrair_open_product_modal, _normalizar


def test_extrai_open_product_modal_do_html():
    html = '''
    <div onclick='openProductModal({"id":123,"nome":"X-Burger","descricao":"Pao e carne","preco_display":"R$ 25,90","imagem_url":"https://img.exemplo/x.webp","categoria_nome":"Lanches"})'>Abrir</div>
    <div onclick='openProductModal({"id":124,"nome":"Batata","preco":12.5,"categoria_nome":"Porcoes"})'>Abrir</div>
    '''
    itens = extrair_open_product_modal(html)
    assert len(itens) == 2
    payload = _normalizar(itens)
    assert payload["products"][0]["name"] == "X-Burger"
    assert payload["products"][0]["price"] == 25.90
    assert payload["products"][0]["category"] == "Lanches"
    assert payload["products"][1]["price"] == 12.5


def test_ignora_modal_invalido_e_deduplica_id():
    html = '''
    <button onclick='openProductModal({"id":1,"nome":"Produto A","preco":10})'></button>
    <button onclick='openProductModal({"id":1,"nome":"Produto A repetido","preco":10})'></button>
    <button onclick='openProductModal({objeto_invalido})'></button>
    '''
    itens = extrair_open_product_modal(html)
    assert len(itens) == 1
    assert str(itens[0]["id"]) == "1"
