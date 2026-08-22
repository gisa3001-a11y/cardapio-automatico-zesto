from platform_specialized_probe import _json_frames, _coletar_documentos_firestore
from generic_preview import gerar_previa_de_payload


def test_json_frames_webchannel_com_prefixos():
    texto = '18\n[[0,[{"targetChange":{"targetIds":[1]}}]]]\n127\n[[1,[{"documentChange":{"document":{"name":"projects/x/documents/produtos/p1","fields":{"name":{"stringValue":"X-Burger"},"price":{"doubleValue":25.9},"category":{"stringValue":"Lanches"}}}}}]]]\n'
    frames = _json_frames(texto)
    assert len(frames) >= 2
    docs = []
    for frame in frames:
        _coletar_documentos_firestore(frame, docs)
    assert len(docs) == 1
    assert docs[0]["name"] == "X-Burger"
    assert docs[0]["price"] == 25.9


def test_documento_firestore_decodificado_vira_produto_generico():
    frame = [{"documentChange": {"document": {
        "name": "projects/x/databases/(default)/documents/produtos/p1",
        "fields": {
            "name": {"stringValue": "Pizza Calabresa"},
            "price": {"doubleValue": 42.0},
            "category": {"stringValue": "Pizzas"},
            "image": {"stringValue": "https://img.exemplo/pizza.jpg"},
        },
    }}}]
    docs = []
    _coletar_documentos_firestore(frame, docs)
    previa = gerar_previa_de_payload({"documents": docs})
    assert len(previa.produtos) == 1
    assert previa.produtos[0].nome == "Pizza Calabresa"
    assert previa.produtos[0].preco == 42.0
