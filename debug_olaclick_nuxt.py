"""Diagnóstico somente-leitura da estrutura Nuxt real da Ola Click.

Não altera o parser nem o XLSX. O objetivo é provar onde variantes/opções ficam
antes de qualquer correção de produção.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from playwright.sync_api import sync_playwright

from fetchers import _nuxt_devalue_decode

URL = "https://la-petite-5.ola.click/products"
OUT = Path("artifacts/olaclick_nuxt.json")


def _shape(obj: Any, depth: int = 2):
    if depth < 0:
        return type(obj).__name__
    if isinstance(obj, dict):
        return {str(k): _shape(v, depth - 1) for k, v in list(obj.items())[:30]}
    if isinstance(obj, list):
        return [_shape(v, depth - 1) for v in obj[:5]]
    if obj is None:
        return None
    return type(obj).__name__


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(locale="pt-BR", viewport={"width": 1440, "height": 1200})
        page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(2500)
        raw_text = page.locator("script#__NUXT_DATA__").text_content(timeout=10000)
        final_url = page.url
        browser.close()

    if not raw_text:
        raise SystemExit("Ola Click: __NUXT_DATA__ ausente.")

    decoded = _nuxt_devalue_decode(json.loads(raw_text))
    store = decoded.get("pinia", {}).get("productsCategories", {}) if isinstance(decoded, dict) else {}
    cats = store.get("productsCategories") or store.get("originalProductsCategories") or []

    products = []
    for cat in cats:
        if not isinstance(cat, dict):
            continue
        for prod in cat.get("products") or []:
            if not isinstance(prod, dict):
                continue
            products.append((cat, prod))

    samples = []
    variant_key_counts = {}
    products_with_variants = 0
    products_with_optionish_keys = 0
    optionish = ("option", "choice", "modifier", "complement", "addon", "extra", "variant")

    for cat, prod in products:
        variants = prod.get("product_variants") or []
        if variants:
            products_with_variants += 1
        keys = set()
        for v in variants:
            if isinstance(v, dict):
                keys.update(v.keys())
                for k in v.keys():
                    variant_key_counts[k] = variant_key_counts.get(k, 0) + 1
        prod_optionish = [k for k in prod.keys() if any(t in str(k).lower() for t in optionish)]
        variant_optionish = sorted(k for k in keys if any(t in str(k).lower() for t in optionish))
        if prod_optionish or variant_optionish:
            products_with_optionish_keys += 1
        if variants and len(samples) < 12:
            samples.append({
                "categoria": cat.get("name"),
                "produto": prod.get("name"),
                "produto_id": prod.get("id"),
                "product_keys": sorted(prod.keys()),
                "product_optionish_keys": sorted(prod_optionish),
                "variant_count": len(variants),
                "variant_keys": sorted(keys),
                "variant_optionish_keys": variant_optionish,
                "variants": variants[:5],
                "shape": _shape(prod, 2),
            })

    report = {
        "url": URL,
        "final_url": final_url,
        "categories": len([c for c in cats if isinstance(c, dict)]),
        "products": len(products),
        "products_with_variants": products_with_variants,
        "products_with_optionish_keys": products_with_optionish_keys,
        "variant_key_counts": dict(sorted(variant_key_counts.items())),
        "samples": samples,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("categories", "products", "products_with_variants", "products_with_optionish_keys")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
