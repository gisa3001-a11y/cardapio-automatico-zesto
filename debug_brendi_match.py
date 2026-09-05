"""Auditoria controlada da Brendi real usada pela bateria V2.

Não altera o parser de produção. Compara o resultado oficial com o __NUXT_DATA__
público, executa o enriquecimento já validado e procura regressões de cobertura,
vínculos, preços, fotos e duplicidades antes de qualquer nova correção.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

import requests

from brendi_nuxt_parser import extrair_pizzas_brendi_nuxt
from brendi_result_enrichment import extrair_nuxt_data_html, enriquecer_resultado_brendi_nuxt
from fetchers import buscar_por_url

URL = "https://pedido.brendi.com.br/pizzaria-tortelli/"


def _norm(value) -> str:
    return " ".join(str(value or "").split()).strip().casefold()


def _flavor_category_id(flavor) -> str:
    path = str((flavor or {}).get("categoryPath") or "")
    return path.rsplit("/", 1)[-1] if "/" in path else ""


def _path_id(path) -> str:
    value = str(path or "")
    return value.rsplit("/", 1)[-1] if "/" in value else value


def main() -> int:
    resultado = buscar_por_url(URL, usar_playwright=False)
    produtos_base = list(resultado.itens or []) + list(resultado.pizzas or [])
    base_snapshot = [
        {
            "codigo": str(getattr(p, "codigo", "") or ""),
            "nome": str(getattr(p, "nome", "") or ""),
            "categoria": str(getattr(p, "categoria", "") or ""),
            "preco": float(getattr(p, "preco", 0) or 0),
            "imagem": str(getattr(p, "imagem", "") or ""),
            "pizza": bool(getattr(p, "pizza", False)),
            "grupos": list(getattr(p, "grupos", []) or []),
        }
        for p in produtos_base
    ]

    resposta = requests.get(
        URL,
        timeout=25,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/131.0 Safari/537.36"
            )
        },
    )
    resposta.raise_for_status()
    nuxt_data = extrair_nuxt_data_html(resposta.text)
    estrutura = extrair_pizzas_brendi_nuxt(nuxt_data)

    categorias = [x for x in (estrutura.get("categories") or []) if isinstance(x, dict)]
    sabores = [x for x in (estrutura.get("flavors") or []) if isinstance(x, dict)]
    sabores_ativos = [x for x in sabores if x.get("active") is not False]
    cat_ids = {str(x.get("id") or "") for x in categorias if x.get("id")}

    size_slugs_by_cat: dict[str, set[str]] = defaultdict(set)
    for cat in categorias:
        cid = str(cat.get("id") or "")
        for size in cat.get("sizes") or []:
            if not isinstance(size, dict) or size.get("active") is False:
                continue
            slug = str(size.get("slug") or "")
            if slug:
                size_slugs_by_cat[cid].add(slug)

    flavor_ids = Counter(str(x.get("id") or "") for x in sabores_ativos if x.get("id"))
    duplicate_flavor_ids = {k: v for k, v in flavor_ids.items() if v > 1}
    semantic_flavors = Counter()
    missing_flavor_images = []
    missing_or_zero_prices = []
    unknown_category = []
    invalid_price_slug = []
    flavors_by_category = Counter()

    for flavor in sabores_ativos:
        fid = str(flavor.get("id") or "")
        nome = str(flavor.get("name") or "")
        cid = _flavor_category_id(flavor)
        flavors_by_category[cid] += 1
        if cid not in cat_ids:
            unknown_category.append({"id": fid, "nome": nome, "category_id": cid})
        if not str(flavor.get("picture") or ""):
            missing_flavor_images.append({"id": fid, "nome": nome, "category_id": cid})

        prices = [p for p in (flavor.get("prices") or []) if isinstance(p, dict)]
        positivos = []
        for price in prices:
            try:
                value = float(price.get("price") or 0)
            except Exception:
                value = 0.0
            slug = str(price.get("slug") or "")
            if value > 0:
                positivos.append((slug, value))
            if slug and size_slugs_by_cat.get(cid) and slug not in size_slugs_by_cat[cid]:
                invalid_price_slug.append({
                    "id": fid,
                    "nome": nome,
                    "category_id": cid,
                    "slug": slug,
                    "slugs_categoria": sorted(size_slugs_by_cat[cid]),
                })
        if not positivos:
            missing_or_zero_prices.append({"id": fid, "nome": nome, "category_id": cid})
        semantic_flavors[(cid, _norm(nome), tuple(sorted(positivos)))] += 1

    duplicate_semantic_flavors = {
        repr(k): v for k, v in semantic_flavors.items() if v > 1
    }

    products_paths_audit = {}
    active_ids = {str(x.get("id") or "") for x in sabores_ativos if x.get("id")}
    all_ids = {str(x.get("id") or "") for x in sabores if x.get("id")}
    for cat in categorias:
        cid = str(cat.get("id") or "")
        declared = {_path_id(x) for x in (cat.get("productsPaths") or []) if _path_id(x)}
        if not declared:
            continue
        products_paths_audit[cid] = {
            "categoria": str(cat.get("name") or ""),
            "declarados": len(declared),
            "presentes_nuxt": len(declared & all_ids),
            "ativos": len(declared & active_ids),
            "inativos_ou_ausentes": sorted(declared - active_ids),
            "ativos_fora_productsPaths": sorted(
                {str(x.get("id") or "") for x in sabores_ativos if _flavor_category_id(x) == cid}
                - declared
            ),
        }

    resultado, auditoria = enriquecer_resultado_brendi_nuxt(resultado, nuxt_data)
    produtos_finais = list(resultado.itens or []) + list(resultado.pizzas or [])

    product_codes = Counter(str(getattr(p, "codigo", "") or "") for p in produtos_finais)
    duplicate_product_codes = {k: v for k, v in product_codes.items() if k and v > 1}
    semantic_products = Counter(
        (
            _norm(getattr(p, "nome", "")),
            _norm(getattr(p, "categoria", "")),
            round(float(getattr(p, "preco", 0) or 0), 6),
            bool(getattr(p, "pizza", False)),
        )
        for p in produtos_finais
    )
    duplicate_semantic_products = {repr(k): v for k, v in semantic_products.items() if v > 1}

    group_ids = {str(getattr(g, "grupo_id", "") or "") for g in (resultado.grupos or [])}
    referenced_groups = {
        str(gid)
        for p in produtos_finais
        for gid in (getattr(p, "grupos", []) or [])
        if gid
    }
    orphan_groups = sorted(group_ids - referenced_groups)
    missing_groups = sorted(referenced_groups - group_ids)

    option_images = sum(1 for g in (resultado.grupos or []) if str(getattr(g, "imagem", "") or ""))
    missing_product_images = [
        {
            "nome": str(getattr(p, "nome", "") or ""),
            "categoria": str(getattr(p, "categoria", "") or ""),
            "pizza": bool(getattr(p, "pizza", False)),
            "codigo": str(getattr(p, "codigo", "") or ""),
        }
        for p in produtos_finais
        if not str(getattr(p, "imagem", "") or "")
    ]

    payload = {
        "url": URL,
        "origem": str(getattr(resultado, "origem", "") or ""),
        "base": {
            "produtos": len(base_snapshot),
            "produtos_com_imagem": sum(1 for p in base_snapshot if p["imagem"]),
            "produtos_sem_imagem": [
                {"codigo": p["codigo"], "nome": p["nome"], "categoria": p["categoria"]}
                for p in base_snapshot if not p["imagem"]
            ],
        },
        "nuxt": {
            "categorias_pizza": len(categorias),
            "sabores_total": len(sabores),
            "sabores_ativos": len(sabores_ativos),
            "sabores_ativos_por_categoria": dict(flavors_by_category),
            "sabores_com_imagem": len(sabores_ativos) - len(missing_flavor_images),
            "sabores_sem_imagem": missing_flavor_images,
            "sabores_sem_preco_positivo": missing_or_zero_prices,
            "slugs_preco_fora_tamanhos_categoria": invalid_price_slug,
            "sabores_categoria_desconhecida": unknown_category,
            "ids_sabor_duplicados": duplicate_flavor_ids,
            "duplicidades_semanticas_sabor": duplicate_semantic_flavors,
            "productsPaths": products_paths_audit,
        },
        "enriquecido": {
            "produtos": len(produtos_finais),
            "pizzas": len(resultado.pizzas or []),
            "opcoes": len(resultado.grupos or []),
            "produtos_com_imagem": len(produtos_finais) - len(missing_product_images),
            "produtos_sem_imagem": missing_product_images,
            "opcoes_com_imagem": option_images,
            "grupos_referenciados": len(referenced_groups),
            "grupos_orfaos": orphan_groups,
            "grupos_referenciados_ausentes": missing_groups,
            "codigos_produto_duplicados": duplicate_product_codes,
            "duplicidades_semanticas_produto": duplicate_semantic_products,
        },
        "auditoria_enriquecimento": auditoria,
    }

    Path("artifacts").mkdir(exist_ok=True)
    Path("artifacts/brendi_match.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    resumo = {
        "base_produtos": payload["base"]["produtos"],
        "final_produtos": payload["enriquecido"]["produtos"],
        "pizzas": payload["enriquecido"]["pizzas"],
        "sabores_ativos": payload["nuxt"]["sabores_ativos"],
        "opcoes": payload["enriquecido"]["opcoes"],
        "fotos_produtos": payload["enriquecido"]["produtos_com_imagem"],
        "fotos_opcoes": payload["enriquecido"]["opcoes_com_imagem"],
        "grupos_orfaos": len(orphan_groups),
        "grupos_ausentes": len(missing_groups),
        "duplicidades_produto": len(duplicate_product_codes) + len(duplicate_semantic_products),
        "duplicidades_sabor": len(duplicate_flavor_ids) + len(duplicate_semantic_flavors),
        "anomalias_preco": len(missing_or_zero_prices) + len(invalid_price_slug),
        "anomalias_categoria": len(unknown_category),
    }
    print(json.dumps(resumo, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
