"""Leitor Universal V2 — roteador isolado e seguro.

Nao altera os parsers existentes. Primeiro normaliza e classifica a URL;
depois delega ao buscar_por_url atual. Dominios desconhecidos continuam no
fallback/diagnostico que ja existe em fetchers.py.
"""

from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse, urlunparse


@dataclass(frozen=True)
class DeteccaoURL:
    url_original: str
    url_normalizada: str
    plataforma: Optional[str]
    metodo: str
    confianca: str


def normalizar_url(url: str) -> str:
    valor = (url or "").strip()
    if not valor:
        raise ValueError("Informe a URL do cardapio.")
    if "://" not in valor:
        valor = "https://" + valor
    p = urlparse(valor)
    if p.scheme not in ("http", "https") or not p.netloc:
        raise ValueError("URL de cardapio invalida.")
    host = (p.hostname or "").lower().strip(".")
    if not host:
        raise ValueError("URL de cardapio invalida.")
    porta = f":{p.port}" if p.port else ""
    caminho = p.path or "/"
    # Remove fragmentos (#...) porque nao participam da requisicao HTTP.
    return urlunparse((p.scheme.lower(), host + porta, caminho, "", p.query, ""))


def detectar_url(url: str) -> DeteccaoURL:
    normalizada = normalizar_url(url)
    # Import tardio: o roteador consegue carregar independentemente dos parsers.
    from fetchers import detectar_plataforma
    plataforma = detectar_plataforma(normalizada)
    if plataforma:
        return DeteccaoURL(url, normalizada, plataforma, "dominio", "alta")
    return DeteccaoURL(url, normalizada, None, "fallback-universal", "a-confirmar")


def ler_url_universal(url: str, usar_playwright: bool = True):
    """Retorna (resultado, deteccao), preservando o leitor oficial atual."""
    deteccao = detectar_url(url)
    from fetchers import buscar_por_url
    resultado = buscar_por_url(deteccao.url_normalizada, usar_playwright=usar_playwright)
    return resultado, deteccao
