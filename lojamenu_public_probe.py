"""Leitura publica deterministica do Loja.Menu via Firestore REST.

Usa somente as mesmas consultas publicas feitas pelo catalogo web. Primeiro
localiza a loja pelo campo `link`; depois consulta as subcolecoes `produtos` e
`categorias` sob o documento da loja. Nenhuma rotina gera XLSX.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple
from urllib.parse import urlparse

import requests

PROJECT = "webcatalogo-1"
BASE = f"https://firestore.googleapis.com/v1/projects/{PROJECT}/databases/(default)/documents"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/151 Safari/537.36",
    "Content-Type": "application/json",
}


def _firestore_value(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    if "nullValue" in value:
        return None
    for chave in ("stringValue", "timestampValue", "referenceValue", "bytesValue"):
        if chave in value:
            return value.get(chave)
    if "booleanValue" in value:
        return bool(value.get("booleanValue"))
    if "integerValue" in value:
        try:
            return int(value.get("integerValue"))
        except Exception:
            return value.get("integerValue")
    if "doubleValue" in value:
        try:
            return float(value.get("doubleValue"))
        except Exception:
            return value.get("doubleValue")
    if "arrayValue" in value:
        vals = (value.get("arrayValue") or {}).get("values") or []
        return [_firestore_value(v) for v in vals]
    if "mapValue" in value:
        fields = (value.get("mapValue") or {}).get("fields") or {}
        return {str(k): _firestore_value(v) for k, v in fields.items()}
    return {str(k): _firestore_value(v) for k, v in value.items()}


def _decode_rows(rows: Any) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if not isinstance(rows, list):
        return out
    for row in rows:
        if not isinstance(row, dict):
            continue
        doc = row.get("document")
        if not isinstance(doc, dict) or not isinstance(doc.get("fields"), dict):
            continue
        item = {str(k): _firestore_value(v) for k, v in doc["fields"].items()}
        item["_firestore_document"] = doc.get("name") or ""
        out.append(item)
    return out


def _slug(url: str) -> str:
    path = (urlparse(url).path or "").strip("/")
    return path.split("/", 1)[0].strip() if path else ""


def _api_key(session: requests.Session, timeout: int) -> str:
    """Lê a chave web pública do bundle Flutter em vez de mantê-la no código."""
    for bundle in (
        "https://loja.menu/main.dart.js?version=40",
        "https://loja.menu/main.dart.js",
    ):
        try:
            r = session.get(bundle, headers=HEADERS, timeout=timeout)
            r.raise_for_status()
            m = re.search(r"AIza[0-9A-Za-z_-]{30,50}", r.text or "")
            if m:
                return m.group(0)
        except Exception:
            continue
    return ""


def _run_query(session: requests.Session, endpoint: str, body: Dict[str, Any], key: str, timeout: int) -> List[Dict[str, Any]]:
    params = {"key": key} if key else None
    r = session.post(endpoint, params=params, headers=HEADERS, json=body, timeout=timeout)
    r.raise_for_status()
    return _decode_rows(r.json())


def _query_collection(session: requests.Session, parent_doc_name: str, collection: str, key: str, timeout: int) -> List[Dict[str, Any]]:
    marker = f"/documents/"
    if marker not in parent_doc_name:
        return []
    parent = parent_doc_name.split(marker, 1)[1].strip("/")
    endpoint = f"{BASE}/{parent}:runQuery"
    body = {
        "structuredQuery": {
            "from": [{"collectionId": collection}],
            "orderBy": [{"field": {"fieldPath": "__name__"}, "direction": "ASCENDING"}],
        }
    }
    return _run_query(session, endpoint, body, key, timeout)


def probe_lojamenu_publico(url: str, timeout: int = 25) -> List[Tuple[str, Any]]:
    if "loja.menu" not in (url or "").lower():
        return []
    slug = _slug(url)
    if not slug:
        return []

    session = requests.Session()
    key = _api_key(session, timeout)

    # Consulta observada no proprio catalogo: lojas WHERE link == slug LIMIT 1.
    loja_body = {
        "structuredQuery": {
            "from": [{"collectionId": "lojas"}],
            "where": {
                "fieldFilter": {
                    "field": {"fieldPath": "link"},
                    "op": "EQUAL",
                    "value": {"stringValue": slug},
                }
            },
            "limit": 1,
        }
    }
    try:
        lojas = _run_query(session, f"{BASE}:runQuery", loja_body, key, timeout)
    except Exception:
        return []
    if not lojas:
        return []

    loja = lojas[0]
    parent_name = str(loja.get("_firestore_document") or "")
    if not parent_name:
        return []

    try:
        produtos = _query_collection(session, parent_name, "produtos", key, timeout)
    except Exception:
        produtos = []
    try:
        categorias = _query_collection(session, parent_name, "categorias", key, timeout)
    except Exception:
        categorias = []

    # Mantemos a loja junto porque ela carrega ordemProdutos e personalizacoes,
    # úteis para a camada universal relacionar itens e adicionais.
    documentos: List[Dict[str, Any]] = []
    documentos.extend(produtos)
    documentos.extend(categorias)
    documentos.append(loja)

    if len(produtos) < 3:
        return []
    return [("specialized:loja-menu-firestore-rest", {"documents": documentos})]
