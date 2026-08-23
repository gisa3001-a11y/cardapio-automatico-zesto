from rapidfood_public_probe import extrair_open_product_modal, extrair_cards_semanticos_html, _normalizar


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


def test_extrai_cards_semanticos_por_h2_h3_preco():
    html = '''
    <main>
      <h2>Pratos</h2>
      <article><h3>Frango Grelhado</h3><p>Arroz, feijao e fritas.</p><span>R$ 20,00</span><button>Adicionar</button></article>
      <article><h3>Bife Acebolado</h3><p>Arroz e feijao.</p><span>R$ 29,90</span><button>Add to cart</button></article>
      <h2>Bebidas</h2>
      <article><h3>Refrigerante</h3><span>R$ 7,00</span><img src="https://img.example/refri.jpg"><button>Adicionar</button></article>
      <aside><h3>Cart</h3><span>Total: R$ 0,00</span></aside>
    </main>
    '''
    itens = extrair_cards_semanticos_html(html)
    assert len(itens) == 3
    assert itens[0]["name"] == "Frango Grelhado"
    assert itens[0]["price"] == 20.0
    assert itens[0]["category"] == "Pratos"
    assert itens[2]["category"] == "Bebidas"
    assert itens[2]["image"] == "https://img.example/refri.jpg"


def test_semantico_deduplica_mesmo_nome_e_preco():
    html = '''
    <h2>Destaques</h2>
    <div><h3>Produto A</h3><span>R$ 10,00</span><button>Adicionar</button></div>
    <h2>Todos</h2>
    <div><h3>Produto A</h3><span>R$ 10,00</span><button>Adicionar</button></div>
    '''
    itens = extrair_cards_semanticos_html(html)
    assert len(itens) == 1
