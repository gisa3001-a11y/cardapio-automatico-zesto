"""Auditoria somente-leitura da Ola Click real usada pela bateria V2.

Compara o resultado oficial com o __NUXT_DATA__ público e o enriquecimento já
validado. Procura regressões em cobertura, fotos, preços, variantes, vínculos e
duplicidades sem alterar o parser de produção.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from playwright.sync_api import sync_playwright

from fetchers import _nuxt_devalue_decode, buscar_por_url
from olaclick_variant_enrichment import enriquecer_resultado_olaclick_variantes

URL = "https://la-petite-5.ola.click/products"
OUT = Path("artifacts/olaclick_quality.json")


def _norm(value) -> str:
    return " ".join(str(value or "").split()).strip().casefold()


def main() -> int:
    resultado = buscar_por_url(URL, usar_playwright=False)
    produtos_base = list(resultado.itens or []) + list(resultado.pizzas or [])
    base_precos = {str(getattr(p, "codigo", "") or ""): float(getattr(p, "preco", 0) or 0) for p in produtos_base}

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

    raw = json.loads(raw_text)
    decoded = _nuxt_devalue_decode(raw)
    store = decoded.get("pinia", {}).get("productsCategories", {}) if isinstance(decoded, dict) else {}
    cats = store.get("productsCategories") or store.get("originalProductsCategories") or []

    produtos_nuxt = []
    for cat in cats:
        if not isinstance(cat, dict) or cat.get("visible") is False:
            continue
        if str(cat.get("type") or "").upper() == "FAVORITE":
            continue
        for prod in cat.get("products") or []:
            if isinstance(prod, dict) and prod.get("visible") is not False:
                produtos_nuxt.append((cat, prod))

    ids = Counter(str(p.get("id") or "") for _, p in produtos_nuxt if p.get("id"))
    duplicate_ids = {k: v for k, v in ids.items() if v > 1}
    semantic = Counter()
    missing_images = []
    invalid_variants = []
    selectable_products = []

    for cat, prod in produtos_nuxt:
        pid = str(prod.get("id") or "")
        nome = str(prod.get("name") or "")
        categoria = str(cat.get("name") or "")
        if not str(prod.get("picture") or prod.get("image") or prod.get("image_url") or ""):
            missing_images.append({"id": pid, "nome": nome, "categoria": categoria})

        variants = [v for v in (prod.get("product_variants") or []) if isinstance(v, dict)]
        nomeadas = []
        precos = []
        for v in variants:
            vnome = str(v.get("name") or "").strip()
            try:
                cents = int(v.get("price"))
            except Exception:
                invalid_variants.append({"produto_id": pid, "produto": nome, "variant": v})
                continue
            if cents < 0:
                invalid_variants.append({"produto_id": pid, "produto": nome, "variant": v})
                continue
            precos.append(cents / 100.0)
            if vnome:
                nomeadas.append((vnome, cents / 100.0))

        if len(nomeadas) >= 2:
            selectable_products.append({
                "id": pid,
                "produto": nome,
                "categoria": categoria,
                "variantes": nomeadas,
                "base_esperada": min(x[1] for x in nomeadas),
            })
        semantic[(categoria.casefold(), _norm(nome), tuple(sorted(precos)))] += 1

    duplicate_semantic = {repr(k): v for k, v in semantic.items() if v > 1}

    resultado, auditoria = enriquecer_resultado_olaclick_variantes(resultado, raw)
    produtos_finais = list(resultado.itens or []) + list(resultado.pizzas or [])
    grupos = list(resultado.grupos or [])
    group_ids = {str(getattr(g, "grupo_id", "") or "") for g in grupos}
    referenced = {str(gid) for p in produtos_finais for gid in (getattr(p, "grupos", []) or []) if gid}

    final_by_id = {str(getattr(p, "codigo", "") or ""): p for p in produtos_finais}
    price_mismatches = []
    final_value_mismatches = []
    for item in selectable_products:
        pid = item["id"]
        p = final_by_id.get(pid)
        if p is None:
            price_mismatches.append({"id": pid, "motivo": "produto selecionavel ausente no resultado final"})
            continue
        base = round(float(getattr(p, "preco", 0) or 0), 2)
        expected = round(float(item["base_esperada"]), 2)
        if base != expected:
            price_mismatches.append({"id": pid, "produto": item["produto"], "esperado": expected, "final": base})
        gid = f"olaclick-variant-{pid}"
        opts = [g for g in grupos if str(getattr(g, "grupo_id", "") or "") == gid]
        finals = sorted(round(base + float(getattr(g, "preco", 0) or 0), 2) for g in opts)
        expected_finals = sorted(round(v, 2) for _, v in item["variantes"])
        if finals != expected_finals:
            final_value_mismatches.append({"id": pid, "produto": item["produto"], "esperado": expected_finals, "final": finals})

    product_codes = Counter(str(getattr(p, "codigo", "") or "") for p in produtos_finais)
    duplicate_product_codes = {k: v for k, v in product_codes.items() if k and v > 1}
    option_semantic = Counter(
        (
            str(getattr(g, "grupo_id", "") or ""),
            _norm(getattr(g, "nome", "")),
            round(float(getattr(g, "preco", 0) or 0), 6),
        )
        for g in grupos
    )
    duplicate_options = {repr(k): v for k, v in option_semantic.items() if v > 1}

    report = {
        "url": URL,
        "final_url": final_url,
        "base_produtos": len(produtos_base),
        "nuxt_produtos": len(produtos_nuxt),
        "final_produtos": len(produtos_finais),
        "categorias": len([c for c in cats if isinstance(c, dict) and c.get("visible") is not False and str(c.get("type") or "").upper() != "FAVORITE"]),
        "produtos_com_escolha": len(selectable_products),
        "opcoes_materializadas": auditoria.get("opcoes_materializadas", 0),
        "produtos_vinculados": auditoria.get("produtos_vinculados", 0),
        "fotos_produtos": sum(1 for p in produtos_finais if str(getattr(p, "imagem", "") or "")),
        "fotos_ausentes_nuxt": len(missing_images),
        "grupos_orfaos": sorted(group_ids - referenced),
        "grupos_ausentes": sorted(referenced - group_ids),
        "duplicidades_id_nuxt": duplicate_ids,
        "duplicidades_semanticas_nuxt": duplicate_semantic,
        "duplicidades_codigo_final": duplicate_product_codes,
        "duplicidades_opcao_final": duplicate_options,
        "variantes_invalidas": invalid_variants,
        "anomalias_preco_base": price_mismatches,
        "anomalias_valor_final_variantes": final_value_mismatches,
        "precos_base_alterados": sum(1 for p in produtos_finais if str(getattr(p, "codigo", "") or "") in base_precos and round(float(getattr(p, "preco", 0) or 0), 2) != round(base_precos[str(getattr(p, "codigo", "") or "")], 2)),
        "selecionaveis": selectable_products,
        "auditoria_enriquecimento": auditoria,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    summary = {
        "produtos": report["final_produtos"],
        "categorias": report["categorias"],
        "produtos_com_escolha": report["produtos_com_escolha"],
        "opcoes": report["opcoes_materializadas"],
        "vinculados": report["produtos_vinculados"],
        "fotos": report["fotos_produtos"],
        "grupos_orfaos": len(report["grupos_orfaos"]),
        "grupos_ausentes": len(report["grupos_ausentes"]),
        "duplicidades": sum(len(report[k]) for k in ("duplicidades_id_nuxt", "duplicidades_semanticas_nuxt", "duplicidades_codigo_final", "duplicidades_opcao_final")),
        "anomalias_preco": len(price_mismatches) + len(final_value_mismatches) + len(invalid_variants),
    }
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
