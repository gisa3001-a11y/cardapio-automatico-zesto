"""Auditoria somente-leitura da loja real Saipos usada pela bateria V2.

Compara a resposta publica /sales/view-data com a conversao usada pelo probe Saipos.
Nao altera o parser de producao. Procura perda de cobertura, imagens, grupos/vinculos,
duplicidades e, principalmente, variacoes de produto/opcao que o conversor possa
estar achatando ao escolher apenas a primeira variacao habilitada.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from saipos_public_probe import HEADERS, _converter_view_data, _primeiro_id_loja, _raiz_view_data, _to_float

STORE_URL = "https://xisda15.saipos.com/home"
OUT = Path("artifacts/saipos_quality.json")


def _norm(v: Any) -> str:
    return " ".join(str(v or "").split()).strip().lower()


def _enabled(obj: dict[str, Any]) -> bool:
    return str(obj.get("enabled") or "Y").upper() != "N"


def _variation_signature(v: dict[str, Any], price_key: str) -> tuple[str, float]:
    nome = _norm(
        v.get("desc_store_item_variation")
        or v.get("desc_store_choice_item_variation")
        or v.get("description")
        or v.get("name")
        or v.get("desc")
    )
    return nome, round(_to_float(v.get(price_key)), 6)


def main() -> int:
    dominio = (urlparse(STORE_URL).hostname or "").strip()
    r = requests.get(
        "https://delivery-api.saipos.com/v1/stores",
        params={"filter": '{"domain_name":"' + dominio + '","is_table_module":false}'},
        headers=HEADERS,
        timeout=45,
    )
    r.raise_for_status()
    store_id = _primeiro_id_loja(r.json())
    if not store_id:
        raise SystemExit("Saipos: loja nao localizada pela API publica.")

    v = requests.get(
        f"https://delivery-api.saipos.com/v1/stores/{store_id}/sales/view-data",
        headers=HEADERS,
        timeout=45,
    )
    v.raise_for_status()
    raiz = _raiz_view_data(v.json())
    if not isinstance(raiz, dict):
        raise SystemExit("Saipos: view-data nao retornou objeto utilizavel.")

    raw_items = [x for x in (raiz.get("items") or []) if isinstance(x, dict)]
    raw_choices = [x for x in (raiz.get("choices") or []) if isinstance(x, dict)]
    converted = _converter_view_data(raiz)
    products = [x for x in (converted.get("products") or []) if isinstance(x, dict)]

    active_raw_ids: set[str] = set()
    raw_product_ids: Counter[str] = Counter()
    semantic_products: Counter[tuple[str, str]] = Counter()
    raw_images = 0
    raw_links: list[tuple[str, str]] = []
    missing_choice_links: list[dict[str, str]] = []
    product_multi_variations: list[dict[str, Any]] = []
    product_distinct_price_variations: list[dict[str, Any]] = []

    choices_map = {
        str(g.get("id_store_choice")): g
        for g in raw_choices
        if g.get("id_store_choice") is not None
    }

    for item in raw_items:
        cat = item.get("category_item") or {}
        if isinstance(cat, dict) and str(cat.get("enabled") or "Y").upper() == "N":
            continue
        nome = str(item.get("desc_store_item") or "").strip()
        if not nome:
            continue
        pid = str(item.get("id_store_item") or "")
        active_raw_ids.add(pid)
        raw_product_ids[pid] += 1
        semantic_products[(_norm(nome), _norm(cat.get("desc_store_category_item") if isinstance(cat, dict) else ""))] += 1
        if item.get("img_path"):
            raw_images += 1

        vars_enabled = [x for x in (item.get("variations") or []) if isinstance(x, dict) and _enabled(x)]
        sigs = [_variation_signature(x, "price") for x in vars_enabled]
        if len(sigs) > 1:
            entry = {"id": pid, "nome": nome, "variacoes": sigs}
            product_multi_variations.append(entry)
            if len({p for _, p in sigs}) > 1:
                product_distinct_price_variations.append(entry)

        for link in item.get("choices") or []:
            if not isinstance(link, dict) or link.get("id_store_choice") is None:
                continue
            gid = str(link.get("id_store_choice"))
            raw_links.append((pid, gid))
            if gid not in choices_map:
                missing_choice_links.append({"produto_id": pid, "produto": nome, "grupo_id": gid})

    choice_ids: Counter[str] = Counter()
    semantic_choices: Counter[str] = Counter()
    option_multi_variations: list[dict[str, Any]] = []
    option_distinct_price_variations: list[dict[str, Any]] = []
    active_options = 0
    option_images = 0

    for g in raw_choices:
        gid = str(g.get("id_store_choice") or "")
        choice_ids[gid] += 1
        semantic_choices[_norm(g.get("desc_store_choice"))] += 1
        for o in g.get("choice_items") or []:
            if not isinstance(o, dict) or not _enabled(o):
                continue
            onome = str(o.get("desc_store_choice_item") or "").strip()
            if not onome:
                continue
            active_options += 1
            if o.get("img_path"):
                option_images += 1
            vars_enabled = [x for x in (o.get("variations") or []) if isinstance(x, dict) and _enabled(x)]
            sigs = [_variation_signature(x, "aditional_price") for x in vars_enabled]
            if len(sigs) > 1:
                entry = {"grupo_id": gid, "opcao": onome, "variacoes": sigs}
                option_multi_variations.append(entry)
                if len({p for _, p in sigs}) > 1:
                    option_distinct_price_variations.append(entry)

    converted_ids = {str(p.get("id") or "") for p in products}
    converted_links = {
        (str(p.get("id") or ""), str(g.get("id") or ""))
        for p in products
        for g in (p.get("option_groups") or [])
        if isinstance(g, dict)
    }
    converted_option_count = sum(
        len(g.get("options") or [])
        for p in products
        for g in (p.get("option_groups") or [])
        if isinstance(g, dict)
    )

    payload = {
        "url": STORE_URL,
        "store_id": store_id,
        "raw_items_ativos": len(active_raw_ids),
        "convertidos_produtos": len(products),
        "produtos_raw_com_imagem": raw_images,
        "produtos_convertidos_com_imagem": sum(1 for p in products if p.get("image")),
        "raw_choices": len(raw_choices),
        "raw_opcoes_ativas": active_options,
        "raw_opcoes_com_imagem": option_images,
        "raw_vinculos_produto_grupo": len(set(raw_links)),
        "convertidos_vinculos_produto_grupo": len(converted_links),
        "convertidos_opcoes_ocorrencias": converted_option_count,
        "produtos_raw_nao_convertidos": sorted(active_raw_ids - converted_ids),
        "ids_produto_duplicados": {k: n for k, n in raw_product_ids.items() if k and n > 1},
        "duplicidades_semanticas_produto_nome_categoria": {repr(k): n for k, n in semantic_products.items() if n > 1},
        "ids_grupo_duplicados": {k: n for k, n in choice_ids.items() if k and n > 1},
        "nomes_grupo_repetidos": {k: n for k, n in semantic_choices.items() if k and n > 1},
        "vinculos_para_grupo_ausente": missing_choice_links,
        "produtos_com_multiplas_variacoes_habilitadas": product_multi_variations,
        "produtos_com_variacoes_de_precos_distintos": product_distinct_price_variations,
        "opcoes_com_multiplas_variacoes_habilitadas": option_multi_variations,
        "opcoes_com_variacoes_de_precos_distintos": option_distinct_price_variations,
    }

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "raw_produtos": payload["raw_items_ativos"],
        "convertidos": payload["convertidos_produtos"],
        "fotos": payload["produtos_convertidos_com_imagem"],
        "raw_opcoes": payload["raw_opcoes_ativas"],
        "vinculos_raw": payload["raw_vinculos_produto_grupo"],
        "vinculos_convertidos": payload["convertidos_vinculos_produto_grupo"],
        "nao_convertidos": len(payload["produtos_raw_nao_convertidos"]),
        "duplicidades_id": len(payload["ids_produto_duplicados"]),
        "variacoes_produto_multiplas": len(product_multi_variations),
        "variacoes_produto_precos_distintos": len(product_distinct_price_variations),
        "variacoes_opcao_multiplas": len(option_multi_variations),
        "variacoes_opcao_precos_distintos": len(option_distinct_price_variations),
        "vinculos_ausentes": len(missing_choice_links),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
