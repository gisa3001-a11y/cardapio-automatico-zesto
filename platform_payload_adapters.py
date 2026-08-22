"""Adaptadores de payload para plataformas que expõem JSON público mas usam
nomes de campos incompatíveis com a prévia genérica.

A saída permanece no formato genérico e ainda passa por filtros, validação e
bloqueio de XLSX da V2.
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple


def _imagem(value: Any) -> Any:
    if isinstance(value, dict):
        return value
    return value or ""


def _preco_neemo(item: Dict[str, Any]) -> float:
    precos = item.get("prices") or []
    candidatos: List[float] = []
    for p in precos:
        if not isinstance(p, dict) or p.get("enabled") is False:
            continue
        try:
            valor = float(p.get("value") or 0)
        except Exception:
            valor = 0.0
        if valor >= 0:
            candidatos.append(valor)
    if candidatos:
        positivos = [x for x in candidatos if x > 0]
        return min(positivos) if positivos else candidatos[0]
    try:
        return float(item.get("lower_price") or 0)
    except Exception:
        return 0.0


def _grupos_neemo(item: Dict[str, Any]) -> List[Dict[str, Any]]:
    grupos = []
    for raw in item.get("complement_categories") or []:
        if not isinstance(raw, dict) or raw.get("enabled") is False:
            continue
        opcoes = []
        for opt in raw.get("complements") or []:
            if not isinstance(opt, dict) or opt.get("enabled") is False:
                continue
            nome = str(opt.get("title") or "").strip()
            if not nome:
                continue
            opcoes.append({
                "id": opt.get("id"),
                "name": nome,
                "description": opt.get("description") or "",
                "price": opt.get("price") or 0,
                "image": _imagem(opt.get("image")),
            })
        if not opcoes:
            continue
        grupos.append({
            "id": raw.get("id"),
            "name": raw.get("title") or "Adicionais",
            "min": raw.get("minimum_choice") or 0,
            "max": raw.get("maximum_choice") or 1,
            "repeat": bool(raw.get("choose_more_than_one")),
            "items": opcoes,
        })
    return grupos


def adaptar_neemo(payload: Any) -> Any:
    raiz = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(raiz, dict) or not isinstance(raiz.get("categories"), list):
        return payload

    produtos = []
    for categoria in raiz.get("categories") or []:
        if not isinstance(categoria, dict) or categoria.get("enabled") is False:
            continue
        categoria_nome = str(categoria.get("title") or "").strip()
        candidatos = []
        candidatos.extend(x for x in (categoria.get("items") or []) if isinstance(x, dict))
        candidatos.extend(x for x in (categoria.get("pizzas") or []) if isinstance(x, dict))
        for item in candidatos:
            if item.get("enabled") is False or item.get("show_on_menu") is False:
                continue
            nome = str(item.get("title") or "").strip()
            if not nome:
                continue
            produtos.append({
                "id": item.get("id") or item.get("external_code"),
                "name": nome,
                "description": item.get("description") or "",
                "price": _preco_neemo(item),
                "image": _imagem(item.get("image")),
                "category": categoria_nome,
                "options": _grupos_neemo(item),
            })

    return {"products": produtos} if produtos else payload


def adaptar_payload(fonte: str, payload: Any) -> Tuple[Any, str]:
    f = (fonte or "").lower()
    if "neemo.com.br" in f and "/menu" in f and "/menu_settings" not in f:
        adaptado = adaptar_neemo(payload)
        if adaptado is not payload:
            return adaptado, "adaptador-neemo"
    return payload, ""
