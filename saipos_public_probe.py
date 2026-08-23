"""Probe publico e conservador do Saipos para o Leitor Universal V2.

Fluxo:
1. descobre a loja pelo dominio publico;
2. consulta /sales/view-data da propria API publica;
3. converte items/choices para o formato generico esperado pela V2.

Nao gera XLSX e nao envia dados ao estabelecimento.
"""
from __future__ import annotations

from urllib.parse import urlparse
from typing import Any, Dict, List, Tuple
import requests

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/151 Safari/537.36",
    "Accept": "application/json,text/plain,*/*",
}


STORE_HINTS = {
    "domain_name", "store_name", "name_store", "desc_store", "slug", "is_table_module",
    "id_store", "store_id", "idStore",
}


def _parece_loja(obj: Dict[str, Any]) -> bool:
    chaves = {str(k) for k in obj.keys()}
    if chaves & {"id_store", "store_id", "idStore"}:
        return True
    # Um campo generico `id` so e aceito quando o mesmo objeto tem sinais claros
    # de cadastro de loja. Isso evita pegar IDs de wrappers, paginacao ou filtros.
    return "id" in chaves and len(chaves & STORE_HINTS) >= 1


def _primeiro_id_loja(data: Any, depth: int = 0):
    """Localiza um ID de loja mesmo quando a API envolve o resultado em wrappers.

    A resposta publica do Saipos mudou de formato ao longo do tempo (lista direta,
    data/results/stores e wrappers aninhados). A busca e deliberadamente limitada e
    so aceita `id` generico em objetos com sinais de loja.
    """
    if depth > 8:
        return ""
    if isinstance(data, dict):
        if _parece_loja(data):
            for k in ("id_store", "store_id", "idStore", "id"):
                if data.get(k) not in (None, ""):
                    return str(data.get(k))
        # Prioriza wrappers comuns antes de percorrer os demais campos.
        for k in ("data", "stores", "items", "results", "result", "content", "payload"):
            if k in data:
                achado = _primeiro_id_loja(data.get(k), depth + 1)
                if achado:
                    return achado
        for v in data.values():
            if isinstance(v, (dict, list)):
                achado = _primeiro_id_loja(v, depth + 1)
                if achado:
                    return achado
    elif isinstance(data, list):
        for v in data[:100]:
            if isinstance(v, (dict, list)):
                achado = _primeiro_id_loja(v, depth + 1)
                if achado:
                    return achado
    return ""


def _to_float(v: Any) -> float:
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace("R$", "").replace(" ", "")
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except Exception:
        return 0.0


def _raiz_view_data(data: Any) -> Dict[str, Any]:
    """Desembrulha somente wrappers conhecidos ate achar items/choices."""
    atual = data
    for _ in range(7):
        if not isinstance(atual, dict):
            return {}
        if isinstance(atual.get("items"), list) or isinstance(atual.get("choices"), list):
            return atual
        proximo = None
        for k in ("data", "result", "content", "payload", "view_data", "viewData"):
            if isinstance(atual.get(k), dict):
                proximo = atual.get(k)
                break
        if proximo is None:
            return atual
        atual = proximo
    return atual if isinstance(atual, dict) else {}


def _converter_view_data(data: Any) -> Dict[str, Any]:
    data = _raiz_view_data(data)
    if not isinstance(data, dict):
        return {"products": []}

    choices_map = {}
    for g in data.get("choices") or []:
        if isinstance(g, dict) and g.get("id_store_choice") is not None:
            choices_map[str(g.get("id_store_choice"))] = g

    products: List[Dict[str, Any]] = []
    for item in data.get("items") or []:
        if not isinstance(item, dict):
            continue
        cat = item.get("category_item") or {}
        if isinstance(cat, dict) and str(cat.get("enabled") or "Y").upper() == "N":
            continue
        nome = str(item.get("desc_store_item") or "").strip()
        if not nome:
            continue

        preco = 0.0
        for v in item.get("variations") or []:
            if not isinstance(v, dict) or str(v.get("enabled") or "Y").upper() == "N":
                continue
            preco = _to_float(v.get("price"))
            break

        groups = []
        for link in item.get("choices") or []:
            if not isinstance(link, dict) or link.get("id_store_choice") is None:
                continue
            raw_gid = str(link.get("id_store_choice"))
            g = choices_map.get(raw_gid)
            if not isinstance(g, dict):
                continue
            opts = []
            for o in g.get("choice_items") or []:
                if not isinstance(o, dict) or str(o.get("enabled") or "Y").upper() == "N":
                    continue
                onome = str(o.get("desc_store_choice_item") or "").strip()
                if not onome:
                    continue
                adicional = 0.0
                for vv in o.get("variations") or []:
                    if isinstance(vv, dict) and vv.get("aditional_price") is not None:
                        adicional = _to_float(vv.get("aditional_price"))
                        break
                opts.append({
                    "name": onome,
                    "price": adicional,
                    "image": o.get("img_path") or "",
                })
            if not opts:
                continue
            groups.append({
                "id": f"saipos-{raw_gid}",
                "name": g.get("desc_store_choice") or "Adicionais",
                "min": g.get("min_choices") or 0,
                "max": g.get("max_choices") or 1,
                "options": opts,
            })

        products.append({
            "id": str(item.get("id_store_item") or len(products) + 1),
            "name": nome,
            "description": item.get("detail") or item.get("desc_store_item_delivery") or "",
            "category": cat.get("desc_store_category_item") if isinstance(cat, dict) else "",
            "image": item.get("img_path") or "",
            "price": preco,
            "option_groups": groups,
        })

    return {"products": products}


def probe_saipos_publico(url: str, timeout: int = 25) -> List[Tuple[str, Any]]:
    if "saipos.com" not in (url or "").lower():
        return []
    dominio = (urlparse(url).hostname or "").strip()
    if not dominio:
        return []
    try:
        r = requests.get(
            "https://delivery-api.saipos.com/v1/stores",
            params={"filter": '{"domain_name":"' + dominio + '","is_table_module":false}'},
            headers=HEADERS,
            timeout=timeout,
        )
        r.raise_for_status()
        store_id = _primeiro_id_loja(r.json())
        if not store_id:
            return []
        v = requests.get(
            f"https://delivery-api.saipos.com/v1/stores/{store_id}/sales/view-data",
            headers=HEADERS,
            timeout=timeout,
        )
        v.raise_for_status()
        payload = _converter_view_data(v.json())
        if len(payload.get("products") or []) < 1:
            return []
        return [("specialized:saipos-public-api", payload)]
    except Exception:
        return []
