"""Fallback opcional com Playwright para o Leitor Universal V2.

Usado apenas quando a leitura HTTP retorna uma casca SPA sem JSON utilizavel.
Captura respostas JSON publicas carregadas pela propria pagina e devolve payloads
para a mesma previa generica. Nao gera XLSX e nao toca na main.
"""
from dataclasses import dataclass
from typing import Any, List, Tuple


@dataclass
class BrowserProbeResult:
    url_final: str
    payloads: List[Tuple[str, Any]]
    erro: str = ""


def coletar_json_publico(url: str, timeout_ms: int = 25000, max_payloads: int = 40) -> BrowserProbeResult:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        return BrowserProbeResult(url, [], f"Playwright indisponivel: {exc}")

    payloads: List[Tuple[str, Any]] = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 Chrome/151 Safari/537.36"
                )
            )

            def on_response(resp):
                if len(payloads) >= max_payloads:
                    return
                try:
                    ct = (resp.headers.get("content-type") or "").lower()
                    if "json" not in ct:
                        return
                    data = resp.json()
                    payloads.append((f"browser:{resp.url}", data))
                except Exception:
                    pass

            page.on("response", on_response)
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            try:
                page.wait_for_load_state("networkidle", timeout=min(timeout_ms, 12000))
            except Exception:
                pass
            final_url = page.url
            browser.close()
            return BrowserProbeResult(final_url, payloads)
    except Exception as exc:
        return BrowserProbeResult(url, payloads, str(exc))
