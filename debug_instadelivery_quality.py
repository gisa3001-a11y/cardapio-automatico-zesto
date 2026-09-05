"""Diagnóstico somente-leitura da loja real InstaDelivery usada pela bateria V2.

Audita a API pública by-slug sem alterar o parser de produção. O objetivo é
comprovar cobertura e procurar sinais concretos de perda/associação incorreta em:
produtos, categorias, preços, imagens, complementos, vínculos e duplicidades.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import requests

URL = "https://app.instadelivery.com.br/api/stores/by-slug/acaidorafa1"
OUT = Path("artifacts/instadelivery_quality.json")


def _norm(v: Any) -> str:
    return " ".join(str(v or "").split()).strip().lower()


def _price(v: Any) -> float:
    if v in (None, ""):
        return 0.0
    try:
        return float(v)
    except Exception:
        try:
            return float(str(v).replace(".", "").replace(",", "."))
        except Exception:
            return 0.0


def _active(obj: dict[str, Any]) -> bool:
    return not bool(obj.get("is_invisible") or obj.get("deleted_at"))


def main() -> int:
    r = requests.get(
        URL,
        headers={
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/151 Safari/537.36",
        },
        timeout=45,
    )
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, dict):
        raise SystemExit("Payload InstaDelivery não é objeto JSON.")

    groups = [g for g in (data.get("groups") or []) if isinstance(g, dict) and _active(g)]
    products: list[dict[str, Any]] = []
    links: list[tuple[str, str]] = []
    group_signatures: dict[str, set[tuple[Any, ...]]] = defaultdict(set)
    group_occurrences: Counter[str] = Counter()
    option_pairs: set[tuple[str, str, float]] = set()
    option_occurrences = 0
    price_anomalies: list[dict[str, Any]] = []
    missing_images: list[dict[str, Any]] = []
    duplicate_ids: Counter[str] = Counter()
    semantic_products: Counter[tuple[str, float, str]] = Counter()

    for cat in groups:
        cat_name = str(cat.get("name") or "")
        for item in (cat.get("itens") or []):
            if not isinstance(item, dict) or not _active(item):
                continue
            pid = str(item.get("id") or "")
            duplicate_ids[pid] += 1
            name = str(item.get("name") or "")
            price1 = _price(item.get("price1"))
            price2 = _price(item.get("price2"))
            strike = _price(item.get("strike_price"))
            image = str(item.get("image") or "")
            products.append({
                "id": pid,
                "nome": name,
                "categoria": cat_name,
                "price1": price1,
                "price2": price2,
                "strike_price": strike,
                "imagem": image,
            })
            semantic_products[(_norm(name), round(price1, 2), _norm(cat_name))] += 1
            if not image:
                missing_images.append({"id": pid, "nome": name, "categoria": cat_name})
            if price1 <= 0 and (price2 > 0 or strike > 0):
                price_anomalies.append({
                    "id": pid,
                    "nome": name,
                    "price1": price1,
                    "price2": price2,
                    "strike_price": strike,
                })

            for cg in (item.get("complementos") or []):
                if not isinstance(cg, dict) or not _active(cg):
                    continue
                gid = str(cg.get("id") or "")
                if not gid:
                    continue
                opts = []
                for opt in (cg.get("complements") or []):
                    if not isinstance(opt, dict) or not _active(opt):
                        continue
                    oname = str(opt.get("name") or "")
                    oprice = _price(opt.get("price"))
                    oid = str(opt.get("id") or "")
                    opts.append((oid, _norm(oname), round(oprice, 6)))
                    option_occurrences += 1
                    option_pairs.add((gid, oid or _norm(oname), round(oprice, 6)))
                if not opts:
                    continue
                group_occurrences[gid] += 1
                links.append((pid, gid))
                signature = (
                    _norm(cg.get("name")),
                    int(cg.get("min") or 0),
                    int(cg.get("max") or 1),
                    tuple(opts),
                )
                group_signatures[gid].add(signature)

    conflicts = {
        gid: [repr(sig) for sig in sigs]
        for gid, sigs in group_signatures.items()
        if len(sigs) > 1
    }
    dup_product_ids = {k: v for k, v in duplicate_ids.items() if k and v > 1}
    dup_semantic = {
        repr(k): v for k, v in semantic_products.items() if v > 1
    }

    payload = {
        "url": URL,
        "categorias_ativas": len(groups),
        "produtos_ativos": len(products),
        "produtos_com_imagem": sum(1 for p in products if p["imagem"]),
        "produtos_sem_imagem": len(missing_images),
        "grupos_ids_unicos": len(group_signatures),
        "grupos_ocorrencias": sum(group_occurrences.values()),
        "opcoes_ocorrencias": option_occurrences,
        "opcoes_unicas_por_grupo": len(option_pairs),
        "vinculos_produto_grupo": len(set(links)),
        "grupos_com_assinaturas_conflitantes": conflicts,
        "ids_produto_duplicados": dup_product_ids,
        "duplicidades_semanticas_nome_preco_categoria": dup_semantic,
        "anomalias_price1_zero_com_outro_preco": price_anomalies,
        "amostra_sem_imagem": missing_images[:20],
        "amostra_produtos": products[:20],
    }

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "categorias_ativas": payload["categorias_ativas"],
        "produtos_ativos": payload["produtos_ativos"],
        "produtos_com_imagem": payload["produtos_com_imagem"],
        "grupos_ids_unicos": payload["grupos_ids_unicos"],
        "opcoes_unicas_por_grupo": payload["opcoes_unicas_por_grupo"],
        "vinculos_produto_grupo": payload["vinculos_produto_grupo"],
        "conflitos_grupo": len(conflicts),
        "duplicidades_id": len(dup_product_ids),
        "duplicidades_semanticas": len(dup_semantic),
        "anomalias_preco": len(price_anomalies),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
