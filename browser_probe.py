"""Fallback opcional com Playwright para o Leitor Universal V2.

Usado quando a leitura HTTP retorna uma casca SPA, falha ou nao contem JSON
utilizavel. Captura prioritariamente respostas XHR/fetch JSON publicas carregadas
pela propria pagina. Nao gera XLSX e nao toca na main.

V2.4: a mesma URL pode ser chamada varias vezes com corpos POST diferentes
(ex.: Firestore documents:runQuery). A deduplicacao considera tambem o corpo da
requisicao para nao perder consultas posteriores do mesmo endpoint.
"""
from dataclasses import dataclass
import hashlib
from typing import Any, List, Tuple


@dataclass
class BrowserProbeResult:
    url_final: str
    payloads: List[Tuple[str, Any]]
    erro: str = ""


IGNORAR_URL_TERMS = (
    "fontmanifest", "manifest.json", "asset-manifest", "favicon", "translations",
    "locales/", "analytics", "google-analytics", "gtag", "clarity", "hotjar",
)


def _chave_requisicao(resp):
    """Distingue chamadas ao mesmo endpoint quando o POST/body muda."""
    try:
        post_data = resp.request.post_data or ""
    except Exception:
        post_data = ""
    return resp.url, post_data


def _fonte_resposta(resp) -> str:
    """Mantem URL legivel e adiciona hash curto somente quando houver POST."""
    try:
        post_data = resp.request.post_data or ""
    except Exception:
        post_data = ""
    if not post_data:
        return f"browser:{resp.url}"
    digest = hashlib.sha1(post_data.encode("utf-8", "ignore")).hexdigest()[:10]
    return f"browser:{resp.url}#req={digest}"


def coletar_json_publico(url: str, timeout_ms: int = 25000, max_payloads: int = 120) -> BrowserProbeResult:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        return BrowserProbeResult(url, [], f"Playwright indisponivel: {exc}")

    payloads: List[Tuple[str, Any]] = []
    vistos = set()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(
                locale="pt-BR",
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 Chrome/151 Safari/537.36"
                ),
                viewport={"width": 1440, "height": 1200},
            )

            def on_response(resp):
                if len(payloads) >= max_payloads:
                    return
                try:
                    if resp.status < 200 or resp.status >= 300:
                        return
                    req_type = (resp.request.resource_type or "").lower()
                    ct = (resp.headers.get("content-type") or "").lower()
                    if "json" not in ct:
                        return
                    url_resp = resp.url
                    low = url_resp.lower()
                    # XHR/fetch tem prioridade. JSON estatico so entra quando nao
                    # parece asset/manifest irrelevante.
                    if req_type not in ("xhr", "fetch") and any(t in low for t in IGNORAR_URL_TERMS):
                        return
                    chave = _chave_requisicao(resp)
                    if chave in vistos:
                        return
                    data = resp.json()
                    vistos.add(chave)
                    payloads.append((_fonte_resposta(resp), data))
                except Exception:
                    pass

            page.on("response", on_response)
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            try:
                page.wait_for_load_state("networkidle", timeout=min(timeout_ms, 12000))
            except Exception:
                pass

            # Alguns catalogos carregam blocos adicionais somente apos a primeira
            # renderizacao/scroll. Um scroll simples nao executa acoes destrutivas.
            try:
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(1800)
                page.evaluate("window.scrollTo(0, 0)")
                page.wait_for_timeout(700)
            except Exception:
                pass

            final_url = page.url
            browser.close()
            return BrowserProbeResult(final_url, payloads)
    except Exception as exc:
        return BrowserProbeResult(url, payloads, str(exc))
