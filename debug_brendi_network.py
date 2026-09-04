"""Diagnóstico público e estrutural da Brendi.

Captura apenas URL/status/tipo e nomes de chaves de respostas JSON carregadas
pela loja pública. Também abre o produto de controle "Grande - 8 Fatias" para
identificar onde a Brendi entrega sabores/adicionais, sem persistir cookies,
cabeçalhos ou dados de sessão.
"""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

URL = "https://pedido.brendi.com.br/pizzaria-tortelli/"


def _shape(obj, depth=0):
    if depth > 2:
        return type(obj).__name__
    if isinstance(obj, dict):
        out = {}
        for k, v in list(obj.items())[:80]:
            out[str(k)] = _shape(v, depth + 1)
        return out
    if isinstance(obj, list):
        return {"type": "list", "len": len(obj), "sample": _shape(obj[0], depth + 1) if obj else None}
    return type(obj).__name__


def _resumo_scripts(page):
    """Resume scripts públicos sem persistir o conteúdo completo."""
    try:
        return page.eval_on_selector_all(
            "script",
            """els => els.map((e, i) => {
                const txt = e.textContent || '';
                const low = txt.toLowerCase();
                return {
                    index: i,
                    id: e.id || '',
                    type: e.type || '',
                    src: e.src || '',
                    length: txt.length,
                    tem_produto_controle: low.includes('grande - 8 fatias'),
                    tem_sabor: low.includes('sabor') || low.includes('flavor'),
                    tem_opcao: low.includes('option') || low.includes('opcao') || low.includes('opção'),
                    tem_grupo: low.includes('group') || low.includes('grupo'),
                };
            }).filter(x => x.length || x.src)""",
        )[:200]
    except Exception:
        return []


def _estrutura_produto_aberto(page):
    """Captura somente texto/estrutura visível do painel/modal aberto."""
    try:
        dados = page.evaluate(
            """() => {
                const visivel = e => {
                    if (!e) return false;
                    const s = getComputedStyle(e);
                    const r = e.getBoundingClientRect();
                    return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
                };
                const candidatos = [...document.querySelectorAll('[role="dialog"], dialog, [class*="modal"], [class*="drawer"], [class*="sheet"], [class*="product"], [class*="produto"]')]
                    .filter(visivel)
                    .map((e, i) => ({
                        index: i,
                        tag: e.tagName,
                        role: e.getAttribute('role') || '',
                        className: typeof e.className === 'string' ? e.className.slice(0, 500) : '',
                        text: (e.innerText || '').trim().slice(0, 8000),
                        inputs: [...e.querySelectorAll('input,button,[role="radio"],[role="checkbox"]')].slice(0, 200).map(x => ({
                            tag: x.tagName,
                            type: x.getAttribute('type') || '',
                            role: x.getAttribute('role') || '',
                            name: x.getAttribute('name') || '',
                            value: x.getAttribute('value') || '',
                            text: (x.innerText || x.getAttribute('aria-label') || '').trim().slice(0, 300)
                        }))
                    }))
                    .filter(x => x.text.toLowerCase().includes('grande - 8 fatias') || x.text.toLowerCase().includes('sabor'));
                return candidatos.slice(0, 20);
            }"""
        )
        return dados if isinstance(dados, list) else []
    except Exception:
        return []


def main():
    from playwright.sync_api import sync_playwright

    rows = []
    seen = set()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(locale="pt-BR", viewport={"width": 1440, "height": 1200})

        def on_response(resp):
            try:
                req = resp.request
                rt = (req.resource_type or "").lower()
                low = resp.url.lower()
                if rt not in ("xhr", "fetch") and not any(x in low for x in ("api", "menu", "product", "produto", "custom", "option", "flavor", "sabor")):
                    return
                key = (resp.url, req.method)
                if key in seen or len(rows) >= 250:
                    return
                seen.add(key)
                row = {
                    "url": resp.url,
                    "host": urlparse(resp.url).netloc,
                    "path": urlparse(resp.url).path,
                    "method": req.method,
                    "resource_type": rt,
                    "status": resp.status,
                    "content_type": (resp.headers.get("content-type") or "").split(";")[0],
                }
                if "json" in row["content_type"]:
                    try:
                        row["json_shape"] = _shape(resp.json())
                    except Exception:
                        pass
                rows.append(row)
            except Exception:
                pass

        page.on("response", on_response)
        page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass

        scripts_antes = _resumo_scripts(page)
        links_antes = page.eval_on_selector_all("a[href]", "els => els.map(e => ({text:(e.innerText||'').trim(), href:e.href})).filter(x => x.href)")
        abriu_produto = False
        erro_click = ""
        try:
            alvo = page.get_by_text("Grande - 8 Fatias", exact=True).last
            alvo.scroll_into_view_if_needed(timeout=10000)
            alvo.click(timeout=10000)
            page.wait_for_timeout(2500)
            try:
                page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass
            abriu_produto = True
        except Exception as exc:
            erro_click = str(exc)

        links_depois = page.eval_on_selector_all("a[href]", "els => els.map(e => ({text:(e.innerText||'').trim(), href:e.href})).filter(x => x.href)")
        scripts_depois = _resumo_scripts(page)
        estrutura_produto = _estrutura_produto_aberto(page)
        try:
            body_text = page.locator("body").inner_text(timeout=5000)
            trecho_body = body_text[:30000]
        except Exception:
            trecho_body = ""
        final_url = page.url
        browser.close()

    payload = {
        "url": URL,
        "final_url": final_url,
        "abriu_produto": abriu_produto,
        "erro_click": erro_click,
        "links_produto_antes": [x for x in links_antes if "produto" in x.get("href", "").lower() or "product" in x.get("href", "").lower()][:100],
        "links_produto_depois": [x for x in links_depois if "produto" in x.get("href", "").lower() or "product" in x.get("href", "").lower()][:100],
        "scripts_antes": scripts_antes,
        "scripts_depois": scripts_depois,
        "estrutura_produto_aberto": estrutura_produto,
        "body_text_publico": trecho_body,
        "requests": rows,
    }
    Path("artifacts").mkdir(exist_ok=True)
    Path("artifacts/brendi_network.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "abriu_produto": abriu_produto,
        "final_url": final_url,
        "requests": len(rows),
        "estruturas_produto": len(estrutura_produto),
        "scripts_com_produto": sum(1 for x in scripts_depois if x.get("tem_produto_controle")),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
