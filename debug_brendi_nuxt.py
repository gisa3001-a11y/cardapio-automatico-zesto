"""Mapeia de forma controlada o __NUXT_DATA__ público da Brendi.

Objetivo: localizar as relações entre produto, escolha do número de sabores,
grupos, opções e preços sem alterar o parser de produção antes de conhecer
o formato com precisão.
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
        return any(_contem_ref(x, alvos, depth + 1) for x in obj[:400])
    if isinstance(obj, dict):
        return any(_contem_ref(v, alvos, depth + 1) for v in list(obj.values())[:400])
    return False


def _resolve_ref(data, idx, depth=0, vistos=None):
    """Resolve uma referência do array achatado do Nuxt.

    Um inteiro encontrado dentro de dict/list aponta para um slot do array.
    Quando esse slot contém um primitivo, o primitivo já é o valor final.
    """
    if vistos is None:
        vistos = set()
    if depth > 9:
        return "<depth-limit>"
    if not isinstance(idx, int) or not (0 <= idx < len(data)):
        return idx
    if idx in vistos:
        return f"<ref:{idx}>"

    vistos = set(vistos)
    vistos.add(idx)
    value = data[idx]

    if not isinstance(value, (dict, list)):
        if isinstance(value, str):
            return value[:4000]
        return value

    if isinstance(value, list):
        return [
            _resolve_ref(data, x, depth + 1, vistos) if isinstance(x, int) else x
            for x in value[:500]
        ]

    out = {}
    for k, v in list(value.items())[:500]:
        if isinstance(v, int):
            out[str(k)] = _resolve_ref(data, v, depth + 1, vistos)
        elif isinstance(v, list):
            out[str(k)] = [
                _resolve_ref(data, x, depth + 1, vistos) if isinstance(x, int) else x
                for x in v[:500]
            ]
        else:
            out[str(k)] = v
    return out


def _expand_container(data, obj, depth=0, vistos=None):
    if vistos is None:
        vistos = set()
    if depth > 6:
        return "<depth-limit>"
    if isinstance(obj, int):
        return {"$ref": obj, "value": _resolve_ref(data, obj, depth + 1, vistos)}
    if isinstance(obj, list):
        return [_expand_container(data, x, depth + 1, vistos) for x in obj[:160]]
    if isinstance(obj, dict):
        return {
            str(k): _expand_container(data, v, depth + 1, vistos)
            for k, v in list(obj.items())[:160]
        }
    if isinstance(obj, str):
        return obj[:2000]
    return obj


def _entidade_interessante(obj):
    if not isinstance(obj, dict):
        return False
    chaves = {str(k) for k in obj}
    return bool(chaves & {
        "name", "title", "productsPaths", "customsPaths", "numOfFlavors",
        "price", "prices", "currentPrice", "extraPrice", "path", "picture", "slug"
    })


def _resolver_campo(data, obj, nome, default=None):
    if not isinstance(obj, dict) or nome not in obj:
        return default
    v = obj.get(nome)
    if isinstance(v, int):
        return _resolve_ref(data, v)
    if isinstance(v, list):
        return [
            _resolve_ref(data, x) if isinstance(x, int) else x
            for x in v
        ]
    return v


def _pizza_snapshot(data):
    """Extrai diretamente entidades de pizza, sem depender da expansão do root.

    Isso evita que listas de preços/pdvCodes fiquem mascaradas por depth-limit
    quando aparecem muito abaixo do objeto menu principal.
    """
    categorias = []
    tamanhos = []
    sabores = []

    for i, obj in enumerate(data):
        if not isinstance(obj, dict):
            continue

        keys = set(obj.keys())
        nome = _resolver_campo(data, obj, "name", "")
        main_category = _resolver_campo(data, obj, "mainCategory", "")
        category_path = _resolver_campo(data, obj, "categoryPath", "")

        if "productsPaths" in keys and str(main_category).lower() == "pizza":
            categorias.append({
                "index": i,
                "id": _resolver_campo(data, obj, "id"),
                "name": nome,
                "calculateType": _resolver_campo(data, obj, "calculateType"),
                "productsPaths": _resolver_campo(data, obj, "productsPaths", []),
                "crusts": _resolver_campo(data, obj, "crusts", []),
                "edges": _resolver_campo(data, obj, "edges", []),
                "customs": _resolver_campo(data, obj, "customs", []),
                "customsPaths": _resolver_campo(data, obj, "customsPaths", []),
            })

        if "numOfFlavors" in keys and "slices" in keys:
            tamanhos.append({
                "index": i,
                "id": _resolver_campo(data, obj, "id"),
                "name": nome,
                "slug": _resolver_campo(data, obj, "slug"),
                "slices": _resolver_campo(data, obj, "slices"),
                "numOfFlavors": _resolver_campo(data, obj, "numOfFlavors", []),
                "customs": _resolver_campo(data, obj, "customs", []),
                "customsPaths": _resolver_campo(data, obj, "customsPaths", []),
            })

        if (
            "prices" in keys
            and isinstance(category_path, str)
            and "/pizza-categories/" in category_path
        ):
            sabores.append({
                "index": i,
                "id": _resolver_campo(data, obj, "id"),
                "name": nome,
                "slug": _resolver_campo(data, obj, "slug"),
                "active": _resolver_campo(data, obj, "active"),
                "categoryPath": category_path,
                "prices": _resolver_campo(data, obj, "prices", []),
                "pdvCodes": _resolver_campo(data, obj, "pdvCodes", []),
                "picture": _resolver_campo(data, obj, "picture", ""),
                "description": _resolver_campo(data, obj, "description", ""),
            })

    return {
        "categories": categorias,
        "sizes": tamanhos,
        "flavors": sabores,
        "counts": {
            "categories": len(categorias),
            "sizes": len(tamanhos),
            "flavors": len(sabores),
        },
    }


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
                "expanded": _expand_container(data, value),
            })
            if len(pais) >= 120:
                break

    entidades = []
    for i, value in enumerate(data):
        if not _entidade_interessante(value):
            continue
        resolved = _resolve_ref(data, i)
        txt = json.dumps(resolved, ensure_ascii=False).lower()
        if (
            "pizza-flavors/" in txt
            or "product-customs/" in txt
            or "grande - 8 fatias" in txt
            or "gigante - 12 fatias" in txt
            or "pizzas grandes" in txt
        ):
            entidades.append({"index": i, "resolved": resolved})
            if len(entidades) >= 160:
                break

    pizzas = _pizza_snapshot(data)

    payload = {
        "url": URL,
        "nuxt_type": type(data).__name__,
        "nuxt_len": len(data),
        "matches": matches[:160],
        "containers_referencing_matches": pais,
        "resolved_entities": entidades,
        "pizza_snapshot": pizzas,
    }
    Path("artifacts").mkdir(exist_ok=True)
    Path("artifacts/brendi_nuxt.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({
        "nuxt_len": len(data),
        "matches": len(matches),
        "containers": len(pais),
        "resolved_entities": len(entidades),
        "pizza_snapshot": pizzas["counts"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
