"""Fallback opcional com Playwright para o Leitor Universal V2.

Usado quando a leitura HTTP retorna uma casca SPA, falha ou nao contem JSON
utilizavel. Captura prioritariamente respostas XHR/fetch JSON publicas carregadas
pela propria pagina. Nao gera XLSX e nao toca na main.
"""
from dataclasses import dataclass
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
                    if url_resp in vistos:
                        return
                    data = resp.json()
                    vistos.add(url_resp)
                    payloads.append((f"browser:{url_resp}", data))
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
