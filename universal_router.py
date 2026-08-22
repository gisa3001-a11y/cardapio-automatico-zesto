"""Leitor Universal V2 — roteador isolado e seguro.

Nao substitui parsers atuais e nao libera XLSX para estruturas desconhecidas.
"""
from dataclasses import dataclass
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


@dataclass(frozen=True)
class DeteccaoURL:
    url_original: str
    url_normalizada: str
    plataforma: Optional[str]
    metodo: str
    confianca: str
    estrategia: str
    motivo: str


DOMINIOS_CONHECIDOS = {
    "anota.ai": ("Anota AI", "playwright-prioritario"),
    "rapidfood.com.br": ("RapidFood", "direto"),
    "byfood.com.br": ("byFood", "direto"),
    "instadelivery.com.br": ("InstaDelivery", "direto"),
    "brendi.com.br": ("Brendi", "playwright-prioritario"),
    "whatsmenu.com.br": ("WhatsMenu", "playwright-prioritario"),
    "ola.click": ("Ola Click", "playwright-prioritario"),
    "cardapioweb.com": ("Cardapio Web", "direto"),
    "saipos.com": ("Saipos", "playwright-prioritario"),
    "menudino.com": ("MenuDino", "direto"),
    "menuintegrado.com.br": ("Menui / Menu Integrado", "playwright-prioritario"),
    "menui.com.br": ("Menui / Menu Integrado", "playwright-prioritario"),
    "meucomercio.com.br": ("MeuComercio", "direto"),
    "atlasautomacao.app.br": ("Atlas Automacao", "diagnostico"),
    "hubt.com.br": ("Hubt", "diagnostico"),
    "theozburger.com.br": ("Yooga Delivery", "diagnostico"),
    "neemo.com.br": ("Neemo", "diagnostico"),
    "entregueja.com.br": ("EntregueJa", "diagnostico"),
    "ecta.com.br": ("ECTA", "diagnostico"),
    "pedidosite.com.br": ("PedidoSite", "diagnostico"),
    "bigd.im": ("BigD", "diagnostico"),
    "my.canva.site": ("Canva Site", "diagnostico"),
    "chefjuliaandrade.com.br": ("Dominio proprio", "diagnostico"),
    "loja.menu": ("Loja.Menu", "diagnostico"),
    "lapizzaiola.com.br": ("Dominio proprio", "diagnostico"),
}

PARAMETROS_RASTREAMENTO = {"fbclid", "gclid", "dclid", "msclkid", "mc_cid", "mc_eid"}
HOSTS_NAO_CARDAPIO = {"chat.whatsapp.com", "wa.me", "api.whatsapp.com"}


def _limpar_query(query: str) -> str:
    pares = []
    for chave, valor in parse_qsl(query or "", keep_blank_values=True):
        c = chave.lower()
        if c in PARAMETROS_RASTREAMENTO or c.startswith("utm_"):
            continue
        pares.append((chave, valor))
    return urlencode(pares, doseq=True)


def normalizar_url(url: str) -> str:
    valor = (url or "").strip()
    if not valor:
        raise ValueError("Informe a URL do cardapio.")
    if "://" not in valor:
        valor = "https://" + valor
    p = urlparse(valor)
    if p.scheme.lower() not in ("http", "https") or not p.netloc:
        raise ValueError("URL de cardapio invalida.")
    host = (p.hostname or "").lower().strip(".")
    if not host:
        raise ValueError("URL de cardapio invalida.")
    if host in HOSTS_NAO_CARDAPIO or host.endswith(".whatsapp.com"):
        raise ValueError("Este link nao e um cardapio publico; parece ser um link do WhatsApp.")
    porta = f":{p.port}" if p.port else ""
    return urlunparse((p.scheme.lower(), host + porta, p.path or "/", "", _limpar_query(p.query), ""))


def _dominio_corresponde(host: str, base: str) -> bool:
    return host == base or host.endswith("." + base)


def _detectar_por_dominio(url: str):
    host = (urlparse(url).hostname or "").lower()
    for base, (plataforma, estrategia) in DOMINIOS_CONHECIDOS.items():
        if _dominio_corresponde(host, base):
            return plataforma, estrategia, base
    return None, None, None


def detectar_url(url: str) -> DeteccaoURL:
    normalizada = normalizar_url(url)
    plataforma, estrategia, base = _detectar_por_dominio(normalizada)
    if plataforma:
        return DeteccaoURL(
            url, normalizada, plataforma, "dominio",
            "alta" if estrategia != "diagnostico" else "dominio-confirmado",
            estrategia, f"Dominio reconhecido: {base}"
        )

    from fetchers import detectar_plataforma
    existente = detectar_plataforma(normalizada)
    if existente:
        return DeteccaoURL(
            url, normalizada, existente, "detector-existente", "alta", "auto",
            "Reconhecido pelo detector atual do projeto"
        )

    return DeteccaoURL(
        url, normalizada, None, "fallback-universal", "a-confirmar", "diagnostico",
        "Dominio ainda nao cadastrado; encaminhar para diagnostico universal"
    )


def diagnosticar_url_universal(url: str):
    """Analisa sinais estruturais; nao gera XLSX."""
    deteccao = detectar_url(url)
    from structure_detector import diagnosticar_estrutura
    return deteccao, diagnosticar_estrutura(deteccao.url_normalizada)


def gerar_previa_url_universal(url: str):
    """Tenta montar previa de produtos; XLSX continua bloqueado."""
    deteccao = detectar_url(url)
    from preview_runner import gerar_previa_universal
    previa = gerar_previa_universal(deteccao.url_normalizada)
    return deteccao, previa


def ler_url_universal(url: str, usar_playwright: bool = True):
    deteccao = detectar_url(url)
    if deteccao.estrategia == "diagnostico":
        return None, deteccao

    from fetchers import buscar_por_url
    resultado = buscar_por_url(deteccao.url_normalizada, usar_playwright=bool(usar_playwright))
    try:
        setattr(resultado, "_leitor_universal", {
            "plataforma": deteccao.plataforma,
            "metodo": deteccao.metodo,
            "confianca": deteccao.confianca,
            "estrategia": deteccao.estrategia,
            "motivo": deteccao.motivo,
            "url_normalizada": deteccao.url_normalizada,
        })
    except Exception:
        pass
    return resultado, deteccao
