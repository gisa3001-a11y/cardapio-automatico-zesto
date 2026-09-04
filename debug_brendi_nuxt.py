"""Mapeia de forma controlada o __NUXT_DATA__ público da Brendi.

Objetivo: localizar as relações entre produto, escolha do número de sabores,
grupos e opções sem alterar o parser de produção antes de conhecer o formato.
"""
from __future__ import annotations

import json
from pathlib import Path

URL = "https://pedido.brendi.com.br/pizzaria-tortelli/"
TERMOS = ("grande - 8 fatias", "gigante - 12 fatias", "sabor", "flavor", "pizzas grandes")


def _contem_ref(obj, alvos, depth=0):
    if depth > 4:
        return False
    if isinstance(obj, int):
        return obj in alvos
    if isinstance(obj, list):
        return any(_contem_ref(x, alvos, depth + 1) for x in obj[:200])
    if isinstance(obj, dict):
        return any(_contem_ref(v, alvos, depth + 1) for v in list(obj.values())[:200])
    return False


def _expand(data, obj, depth=0, vistos=None):
    if vistos is None:
        vistos = set()
    if depth > 4:
        return "<depth-limit>"
    if isinstance(obj, int) and 0 <= obj < len(data):
        if obj in vistos:
            return f"<ref:{obj}>"
        vistos = set(vistos)
        vistos.add(obj)
        return {"$ref": obj, "value": _expand(data, data[obj], depth + 1, vistos)}
    if isinstance(obj, list):
        return [_expand(data, x, depth + 1, vistos) for x in obj[:80]]
    if isinstance(obj, dict):
        return {str(k): _expand(data, v, depth + 1, vistos) for k, v in list(obj.items())[:80]}
    if isinstance(obj, str):
        return obj[:1000]
    return obj


def main():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(locale="pt-BR", viewport={"width": 1440, "height": 1200})
        page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        raw = page.locator("script#__NUXT_DATA__").text_content(timeout=10000) or ""
        browser.close()

    data = json.loads(raw)
    if not isinstance(data, list):
        raise SystemExit("__NUXT_DATA__ não é lista; formato mudou.")

    matches = []
    alvos = set()
    for i, value in enumerate(data):
        if isinstance(value, str):
            low = value.lower()
            if any(t in low for t in TERMOS):
                matches.append({"index": i, "value": value[:2000]})
                alvos.add(i)

    pais = []
    for i, value in enumerate(data):
        if i in alvos or not isinstance(value, (dict, list)):
            continue
        if _contem_ref(value, alvos):
            pais.append({
                "index": i,
                "raw": value,
                "expanded": _expand(data, value),
            })
            if len(pais) >= 80:
                break

    payload = {
        "url": URL,
        "nuxt_type": type(data).__name__,
        "nuxt_len": len(data),
        "matches": matches[:120],
        "containers_referencing_matches": pais,
    }
    Path("artifacts").mkdir(exist_ok=True)
    Path("artifacts/brendi_nuxt.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({
        "nuxt_len": len(data),
        "matches": len(matches),
        "containers": len(pais),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
