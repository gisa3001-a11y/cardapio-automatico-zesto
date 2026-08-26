"""Fallback opcional com Playwright para o Leitor Universal V2.

Usado quando a leitura HTTP retorna uma casca SPA, falha ou nao contem JSON
utilizavel. Captura prioritariamente respostas XHR/fetch JSON publicas carregadas
pela propria pagina. Nao gera XLSX e nao toca na main.

V2.7:
- a mesma URL pode ser chamada varias vezes com corpos POST diferentes;
- apos a renderizacao, tambem coleta JSON embutido no DOM;
- XHR/fetch com Content-Type incorreto tambem e testado quando o corpo realmente
  comeca com { ou [;
- quando nao existe JSON utilizavel, cria um payload conservador a partir de
  cards visiveis que tenham nome + preco em R$, sem clicar nem enviar dados.
"""
from dataclasses import dataclass
import hashlib
import json
import shutil
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
    try:
        post_data = resp.request.post_data or ""
    except Exception:
        post_data = ""
    return resp.url, post_data


def _fonte_resposta(resp) -> str:
    try:
        post_data = resp.request.post_data or ""
    except Exception:
        post_data = ""
    if not post_data:
        return f"browser:{resp.url}"
    digest = hashlib.sha1(post_data.encode("utf-8", "ignore")).hexdigest()[:10]
    return f"browser:{resp.url}#req={digest}"


def _coletar_json_dom(page, payloads: List[Tuple[str, Any]], vistos_dom: set, max_payloads: int):
    if len(payloads) >= max_payloads:
        return
    try:
        scripts = page.locator('script[type="application/json"], script#__NEXT_DATA__, script[data-json]').all()
    except Exception:
        scripts = []

    for idx, script in enumerate(scripts):
        if len(payloads) >= max_payloads:
            break
        try:
            texto = (script.text_content() or "").strip()
            if not texto or len(texto) > 8_000_000:
                continue
            digest = hashlib.sha1(texto.encode("utf-8", "ignore")).hexdigest()
            if digest in vistos_dom:
                continue
            data = json.loads(texto)
            vistos_dom.add(digest)
            sid = script.get_attribute("id") or script.get_attribute("data-json") or str(idx)
            payloads.append((f"browser-dom:{page.url}#script={sid}", data))
        except Exception:
            continue


def _coletar_cards_visiveis(page, payloads: List[Tuple[str, Any]], max_payloads: int):
    """Extrai somente cards visiveis com preco explicito em R$.

    E um fallback para plataformas que renderizam o cardapio no DOM mas nao
    deixam JSON publico facilmente observavel. Exige pelo menos 3 itens unicos
    para reduzir risco de confundir total/carrinho com produto.
    """
    if len(payloads) >= max_payloads:
        return
    try:
        produtos = page.evaluate(
            """
            () => {
              const money = /R\\$\\s*([0-9]{1,4}(?:[.,][0-9]{2})?)/i;
              const bad = /^(?:total|subtotal|frete|taxa(?: de)? entrega|carrinho|checkout|pedido mínimo|desconto|cupom)$/i;
              const sels = [
                '[class*="product" i]', '[class*="produto" i]', '[class*="item" i]',
                '[class*="card" i]', 'article', 'li'
              ];
              const nodes = Array.from(document.querySelectorAll(sels.join(','))).slice(0, 2500);
              const out = [];
              const seen = new Set();
              for (const el of nodes) {
                const style = getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                if (style.display === 'none' || style.visibility === 'hidden' || rect.width < 40 || rect.height < 20) continue;
                const text = (el.innerText || '').replace(/\\s+/g, ' ').trim();
                if (!text || text.length > 900 || !money.test(text)) continue;
                const m = text.match(money);
                if (!m) continue;
                let price = Number(m[1].replace('.', '').replace(',', '.'));
                if (!Number.isFinite(price) || price < 0 || price > 5000) continue;

                let name = '';
                const preferred = el.querySelector('h1,h2,h3,h4,h5,[class*="name" i],[class*="nome" i],[class*="title" i],[class*="titulo" i]');
                if (preferred) name = (preferred.innerText || '').replace(/\\s+/g, ' ').trim();
                if (!name) {
                  const parts = (el.innerText || '').split(/\\n+/).map(x => x.replace(/\\s+/g, ' ').trim()).filter(Boolean);
                  name = parts.find(x => !money.test(x) && x.length >= 2 && x.length <= 180) || '';
                }
                name = name.replace(/R\\$.*$/i, '').trim();
                if (!name || name.length < 2 || name.length > 180 || bad.test(name)) continue;

                let image = '';
                const img = el.querySelector('img');
                if (img) image = img.currentSrc || img.src || '';
                if (image && !/^https?:\\/\\//i.test(image)) image = '';

                let category = '';
                const section = el.closest('section,[class*="category" i],[class*="categoria" i],[class*="section" i],[class*="secao" i]');
                if (section) {
                  const heading = section.querySelector('h1,h2,h3,h4,[class*="category" i],[class*="categoria" i]');
                  if (heading && heading !== el) category = (heading.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 180);
                }

                const key = name.toLowerCase() + '|' + price.toFixed(2);
                if (seen.has(key)) continue;
                seen.add(key);
                out.push({name, price, image, category});
                if (out.length >= 300) break;
              }
              return out;
            }
            """
        )
    except Exception:
        return
    if not isinstance(produtos, list) or len(produtos) < 3:
        return
    payloads.append((f"browser-dom-cards:{page.url}", {"products": produtos}))


def _json_da_resposta(resp, content_type: str, req_type: str):
    """Retorna JSON real sem confiar cegamente no Content-Type."""
    if "json" in content_type:
        try:
            return resp.json()
        except Exception:
            pass

    if req_type not in ("xhr", "fetch"):
        return None
    try:
        texto = (resp.text() or "").lstrip()
    except Exception:
        return None
    if not texto or len(texto) > 8_000_000 or texto[0] not in "[{":
        return None
    try:
        return json.loads(texto)
    except Exception:
        return None


def coletar_json_publico(url: str, timeout_ms: int = 25000, max_payloads: int = 120) -> BrowserProbeResult:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        return BrowserProbeResult(url, [], f"Playwright indisponivel: {exc}")

    payloads: List[Tuple[str, Any]] = []
    vistos = set()
    vistos_dom = set()
        try:
        with sync_playwright() as p:
            chromium_sistema = (
                shutil.which("chromium")
                or shutil.which("chromium-browser")
                or shutil.which("google-chrome")
                or shutil.which("google-chrome-stable")
            )

            if chromium_sistema:
                browser = p.chromium.launch(
                    headless=True,
                    executable_path=chromium_sistema,
                    args=[
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                    ],
                )
            else:
                browser = p.chromium.launch(
                    headless=True,
                    args=[
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                    ],
                )

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
                    low = resp.url.lower()
                    if req_type not in ("xhr", "fetch") and any(
                        t in low for t in IGNORAR_URL_TERMS
                    ):
                        return
                    chave = _chave_requisicao(resp)
                    if chave in vistos:
                        return
                    data = _json_da_resposta(resp, ct, req_type)
                    if data is None:
                        return
                    vistos.add(chave)
                    payloads.append((_fonte_resposta(resp), data))
                except Exception:
                    pass

            page.on("response", on_response)
            page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=timeout_ms,
            )

            try:
                page.wait_for_load_state(
                    "networkidle",
                    timeout=min(timeout_ms, 12000),
                )
            except Exception:
                pass

            _coletar_json_dom(
                page,
                payloads,
                vistos_dom,
                max_payloads,
            )
            _coletar_cards_visiveis(
                page,
                payloads,
                max_payloads,
            )

            try:
                page.evaluate(
                    "window.scrollTo(0, document.body.scrollHeight)"
                )
                page.wait_for_timeout(1800)

                _coletar_json_dom(
                    page,
                    payloads,
                    vistos_dom,
                    max_payloads,
                )
                _coletar_cards_visiveis(
                    page,
                    payloads,
                    max_payloads,
                )

                page.evaluate("window.scrollTo(0, 0)")
                page.wait_for_timeout(700)
            except Exception:
                pass

            final_url = page.url
            browser.close()
            return BrowserProbeResult(final_url, payloads)

    except Exception as exc:
        return BrowserProbeResult(url, payloads, str(exc))
