"""Leitor Universal V2 — roteador isolado e seguro.

Esta camada NAO substitui os parsers atuais. Ela apenas:
1) normaliza a URL;
2) identifica a plataforma por dominio/subdominio;
3) escolhe a estrategia de leitura mais adequada;
4) delega ao buscar_por_url ja existente em fetchers.py.

A main oficial nao usa este arquivo enquanto a V2 estiver em testes.
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
    estrategia: str
    motivo: str


# Dominio-base -> (plataforma, estrategia)
# "direto" = leitor atual pode tentar HTTP/HTML/API primeiro.
# "playwright-prioritario" = pagina normalmente depende de carregamento dinamico.
DOMINIOS_CONHECIDOS = {
    "anota.ai": ("Anota AI", "playwright-prioritario"),
    "rapidfood.com.br": ("RapidFood", "direto"),
    "byfood.com.br": ("byFood", "direto"),
    "instadelivery.com.br": ("InstaDelivery", "direto"),
    "brendi.com.br": ("Brendi", "playwright-prioritario"),
    "ola.click": ("Ola Click", "playwright-prioritario"),
    "cardapioweb.com": ("Cardapio Web", "direto"),
    "saipos.com": ("Saipos", "playwright-prioritario"),
    "menudino.com": ("MenuDino", "direto"),
    "menuintegrado.com.br": ("Menui / Menu Integrado", "playwright-prioritario"),
    "menui.com.br": ("Menui / Menu Integrado", "playwright-prioritario"),
    "meucomercio.com.br": ("MeuComercio", "direto"),
}


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

    porta = f":{p.port}" if p.port else ""
    caminho = p.path or "/"

    # Fragmentos (#...) nao participam da requisicao HTTP.
    # Query string e preservada, pois algumas plataformas usam parametros.
    return urlunparse((p.scheme.lower(), host + porta, caminho, "", p.query, ""))


def _dominio_corresponde(host: str, dominio_base: str) -> bool:
    """Aceita o dominio exato e qualquer subdominio real dele."""
    return host == dominio_base or host.endswith("." + dominio_base)


def _detectar_por_dominio(url_normalizada: str):
    host = (urlparse(url_normalizada).hostname or "").lower()
    for dominio_base, (plataforma, estrategia) in DOMINIOS_CONHECIDOS.items():
        if _dominio_corresponde(host, dominio_base):
            return plataforma, estrategia, dominio_base
    return None, None, None


def detectar_url(url: str) -> DeteccaoURL:
    normalizada = normalizar_url(url)

    plataforma, estrategia, dominio_base = _detectar_por_dominio(normalizada)
    if plataforma:
        return DeteccaoURL(
            url_original=url,
            url_normalizada=normalizada,
            plataforma=plataforma,
            metodo="dominio",
            confianca="alta",
            estrategia=estrategia,
            motivo=f"Dominio reconhecido: {dominio_base}",
        )

    # Segunda opiniao: preserva toda a inteligencia ja existente no projeto.
    from fetchers import detectar_plataforma

    plataforma_existente = detectar_plataforma(normalizada)
    if plataforma_existente:
        return DeteccaoURL(
            url_original=url,
            url_normalizada=normalizada,
            plataforma=plataforma_existente,
            metodo="detector-existente",
            confianca="alta",
            estrategia="auto",
            motivo="Reconhecido pelo detector atual do projeto",
        )

    return DeteccaoURL(
        url_original=url,
        url_normalizada=normalizada,
        plataforma=None,
        metodo="fallback-universal",
        confianca="a-confirmar",
        estrategia="diagnostico",
        motivo="Dominio ainda nao cadastrado; encaminhar para diagnostico universal",
    )


def ler_url_universal(url: str, usar_playwright: bool = True):
    """Retorna (resultado, deteccao) sem alterar os parsers existentes."""
    deteccao = detectar_url(url)

    from fetchers import buscar_por_url

    # Nao forca comportamento novo nos parsers. Apenas garante que plataformas
    # dinamicas possam usar navegador quando o chamador permitir.
    playwright = bool(usar_playwright)
    resultado = buscar_por_url(deteccao.url_normalizada, usar_playwright=playwright)

    # Metadados auxiliares; nao interferem no XLSX nem na validacao.
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
