import unittest

from models import Produto, Resultado
from universal_router import (
    _sanear_classificacao_anota,
    _sanear_classificacao_olaclick,
    detectar_url,
    normalizar_url,
)


class TestUniversalRouter(unittest.TestCase):
    def test_rapidfood(self):
        d = detectar_url("https://rapidfood.com.br/panelamineira")
        self.assertEqual(d.plataforma, "RapidFood")
        self.assertEqual(d.confianca, "alta")
        self.assertEqual(d.estrategia, "direto")
        self.assertEqual(d.url_normalizada, "https://rapidfood.com.br/panelamineira")

    def test_brendi_subdominio_pedido(self):
        d = detectar_url("https://pedido.brendi.com.br/flores-pizzas-artesanais-colina-azul")
        self.assertEqual(d.plataforma, "Brendi")
        self.assertEqual(d.confianca, "alta")
        self.assertEqual(d.estrategia, "playwright-prioritario")
        self.assertEqual(
            d.url_normalizada,
            "https://pedido.brendi.com.br/flores-pizzas-artesanais-colina-azul",
        )

    def test_normaliza_sem_protocolo(self):
        self.assertEqual(
            normalizar_url("rapidfood.com.br/panelamineira"),
            "https://rapidfood.com.br/panelamineira",
        )

    def test_remove_fragmento_mantem_query(self):
        self.assertEqual(
            normalizar_url("https://pedido.brendi.com.br/loja?x=1#produto"),
            "https://pedido.brendi.com.br/loja?x=1",
        )

    def test_nao_confunde_dominio_falso(self):
        d = detectar_url("https://brendi.com.br.exemplo.com/cardapio")
        self.assertNotEqual(d.plataforma, "Brendi")

    def test_anota_vinho_sem_evidencia_semantica_nao_fica_como_pizza(self):
        vinho = Produto(
            codigo="v1",
            nome="Vinho Villena 1L",
            categoria="Vinhos",
            preco=29.9,
            pizza=True,
        )
        resultado = Resultado(itens=[], pizzas=[vinho], origem="Anota AI")

        saneado = _sanear_classificacao_anota(resultado, "Anota AI")

        self.assertEqual(len(saneado.pizzas), 0)
        self.assertEqual(len(saneado.itens), 1)
        self.assertEqual(saneado.itens[0].nome, "Vinho Villena 1L")
        self.assertFalse(saneado.itens[0].pizza)
        self.assertTrue(any("reclassificou 1 vinho" in a for a in saneado.avisos))

    def test_anota_vinho_com_categoria_pizzas_ainda_e_reclassificado(self):
        vinho = Produto(
            codigo="v-real",
            nome="Vinho Concha Y Toro 750ml",
            categoria="Pizzas",
            preco=34.9,
            pizza=True,
        )
        resultado = Resultado(itens=[], pizzas=[vinho], origem="Anota AI")

        saneado = _sanear_classificacao_anota(resultado, "Anota AI")

        self.assertEqual(len(saneado.pizzas), 0)
        self.assertEqual(len(saneado.itens), 1)
        self.assertFalse(saneado.itens[0].pizza)

    def test_anota_vinho_com_descricao_contaminada_ainda_e_reclassificado(self):
        vinho = Produto(
            codigo="v-desc",
            nome="Vinho Cantinho do Vale 2L",
            categoria="Pizzas",
            descricao="Categoria de pizzas e sabores disponíveis.",
            preco=39.9,
            pizza=True,
        )
        resultado = Resultado(itens=[], pizzas=[vinho], origem="Anota AI")

        saneado = _sanear_classificacao_anota(resultado, "Anota AI")

        self.assertEqual(len(saneado.pizzas), 0)
        self.assertEqual(len(saneado.itens), 1)
        self.assertFalse(saneado.itens[0].pizza)

    def test_anota_nao_reclassifica_item_com_evidencia_real_de_pizza(self):
        item = Produto(
            codigo="p1",
            nome="Pizza com Vinho",
            categoria="Pizzas",
            preco=49.9,
            pizza=True,
        )
        resultado = Resultado(itens=[], pizzas=[item], origem="Anota AI")

        saneado = _sanear_classificacao_anota(resultado, "Anota AI")

        self.assertEqual(len(saneado.pizzas), 1)
        self.assertEqual(len(saneado.itens), 0)
        self.assertTrue(saneado.pizzas[0].pizza)

    def test_saneamento_anota_nao_altera_outras_plataformas(self):
        vinho = Produto(
            codigo="v2",
            nome="Vinho da Casa",
            categoria="Vinhos",
            preco=39.9,
            pizza=True,
        )
        resultado = Resultado(itens=[], pizzas=[vinho], origem="Outra")

        saneado = _sanear_classificacao_anota(resultado, "Ola Click")

        self.assertEqual(len(saneado.pizzas), 1)
        self.assertEqual(len(saneado.itens), 0)

    def test_olaclick_pastel_com_pizza_so_na_descricao_volta_para_regular(self):
        pastel = Produto(
            codigo="a14c77f7-5409-4635-a409-b27ca4e0cc08",
            nome="Pastel",
            categoria="Café da Manhã(sex,sab,dom-)",
            descricao="Carne, carne c/ queijo, frango c/ catupiry, queijo e pizza.",
            preco=14.0,
            pizza=True,
        )
        resultado = Resultado(itens=[], pizzas=[pastel], origem="Ola Click")

        saneado = _sanear_classificacao_olaclick(resultado, "Ola Click")

        self.assertEqual(len(saneado.pizzas), 0)
        self.assertEqual(len(saneado.itens), 1)
        self.assertFalse(saneado.itens[0].pizza)
        self.assertTrue(any("reclassificou 1 pastel" in a for a in saneado.avisos))

    def test_olaclick_preserva_pastel_de_pizza(self):
        pastel = Produto(
            codigo="pastel-pizza",
            nome="Pastel de Pizza",
            categoria="Salgados",
            descricao="Mussarela, tomate e orégano.",
            preco=15.0,
            pizza=True,
        )
        resultado = Resultado(itens=[], pizzas=[pastel], origem="Ola Click")

        saneado = _sanear_classificacao_olaclick(resultado, "Ola Click")

        self.assertEqual(len(saneado.pizzas), 1)
        self.assertEqual(len(saneado.itens), 0)
        self.assertTrue(saneado.pizzas[0].pizza)

    def test_saneamento_olaclick_nao_altera_outras_plataformas(self):
        pastel = Produto(
            codigo="pastel-outra",
            nome="Pastel",
            categoria="Salgados",
            descricao="Sabores queijo e pizza.",
            preco=14.0,
            pizza=True,
        )
        resultado = Resultado(itens=[], pizzas=[pastel], origem="Outra")

        saneado = _sanear_classificacao_olaclick(resultado, "Anota AI")

        self.assertEqual(len(saneado.pizzas), 1)
        self.assertEqual(len(saneado.itens), 0)


if __name__ == "__main__":
    unittest.main()
