import unittest

from universal_router import detectar_url, normalizar_url


class TestUniversalRouterV2(unittest.TestCase):
    def test_plataformas_conhecidas(self):
        casos = {
            "https://rapidfood.com.br/panelamineira": "RapidFood",
            "https://pedido.brendi.com.br/flores-pizzas-artesanais-colina-azul": "Brendi",
            "https://whatsmenu.com.br/restauranterecantomineiro?fbclid=abc": "WhatsMenu",
            "https://instadelivery.com.br/acaidorafa1": "InstaDelivery",
            "https://pointdogosasco.byfood.com.br": "byFood",
            "https://pollolokoouroverde.menudino.com/": "MenuDino",
            "https://temperodaleia.saipos.com/": "Saipos",
            "https://app.anota.ai/m/xPELP5xiw": "Anota AI",
            "https://tatys-burger-2.ola.click/products": "Ola Click",
            "https://app.cardapioweb.com/shakepoint_westplaza": "Cardapio Web",
            "https://meucomercio.com.br/AdegaOriom": "MeuComercio",
        }
        for url, esperado in casos.items():
            with self.subTest(url=url):
                self.assertEqual(detectar_url(url).plataforma, esperado)

    def test_dominios_em_diagnostico(self):
        casos = {
            "https://atlasautomacao.app.br/confeitariaandressamarquespds": "Atlas Automacao",
            "https://www.hubt.com.br/oriental-suzano/": "Hubt",
            "https://loja.neemo.com.br/braseiro-choperia-e-espetaria": "Neemo",
            "https://www.ecta.com.br/PizzariaMaisvoce?w=1": "ECTA",
            "https://gordolancheshamburgueria.pedidosite.com.br/?loja=9919": "PedidoSite",
            "https://recantodochurrasco1.bigd.im": "BigD",
            "https://vemdeburger.entregueja.com.br/home": "EntregueJa",
            "https://loja.menu/bombuque": "Loja.Menu",
            "http://www.theozburger.com.br": "Yooga Delivery",
        }
        for url, esperado in casos.items():
            with self.subTest(url=url):
                d = detectar_url(url)
                self.assertEqual(d.plataforma, esperado)
                self.assertEqual(d.estrategia, "diagnostico")

    def test_remove_rastreamento(self):
        url = "https://whatsmenu.com.br/pizzariageovanas?fbclid=123&utm_source=facebook&mesa=4"
        normalizada = normalizar_url(url)
        self.assertNotIn("fbclid", normalizada)
        self.assertNotIn("utm_source", normalizada)
        self.assertIn("mesa=4", normalizada)

    def test_rejeita_whatsapp(self):
        with self.assertRaises(ValueError):
            normalizar_url("https://chat.whatsapp.com/LIXncknUZUK1EJLfKBANL4")


if __name__ == "__main__":
    unittest.main()
