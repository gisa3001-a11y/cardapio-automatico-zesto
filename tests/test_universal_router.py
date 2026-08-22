import unittest

from universal_router import detectar_url, normalizar_url


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


if __name__ == "__main__":
    unittest.main()
