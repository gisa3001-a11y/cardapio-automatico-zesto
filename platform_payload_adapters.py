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


def _numero_hubt(value: Any) -> float:
    if isinstance(value, dict):
        for chave in ("value", "price", "amount"):
            if chave in value:
                return _numero_hubt(value.get(chave))
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        texto = value.strip().replace("R$", "").replace(" ", "")
        if "," in texto:
            texto = texto.replace(".", "").replace(",", ".")
        try:
            return float(texto)
        except Exception:
            return 0.0
    return 0.0


def _preco_hubt(item: Dict[str, Any]) -> float:
    candidatos: List[float] = []
    for chave in ("prices", "price", "value", "amount"):
        if chave not in item:
            continue
        raw = item.get(chave)
        if isinstance(raw, list):
            for p in raw:
                valor = _numero_hubt(p)
                if valor > 0:
                    candidatos.append(valor)
        else:
            valor = _numero_hubt(raw)
            if valor > 0:
                candidatos.append(valor)
    return min(candidatos) if candidatos else 0.0


def _imagem_hubt(item: Dict[str, Any]) -> Any:
    imagens = item.get("images") or []
    if isinstance(imagens, list) and imagens:
        primeira = imagens[0]
        if isinstance(primeira, dict):
            for chave in ("url", "src", "image", "original"):
                if primeira.get(chave):
                    return primeira.get(chave)
        return primeira
    direta = item.get("image") or item.get("imageUrl") or item.get("photo") or ""
    if isinstance(direta, dict):
        for chave in ("url", "src", "original"):
            if direta.get(chave):
                return direta.get(chave)
    return direta


def _tipos_hubt(raw: Any) -> Dict[str, str]:
    """Aceita tanto o formato real (lista) quanto variações antigas/em cache (dict)."""
    tipos: Dict[str, str] = {}
    if isinstance(raw, list):
        for obj in raw:
            if isinstance(obj, dict):
                ident = obj.get("id") or obj.get("_id")
                if ident is not None:
                    tipos[str(ident)] = str(obj.get("name") or obj.get("title") or "")
    elif isinstance(raw, dict):
        for ident, obj in raw.items():
            if isinstance(obj, dict):
                tipos[str(ident)] = str(obj.get("name") or obj.get("title") or "")
            else:
                tipos[str(ident)] = str(obj or "")
    return tipos


def adaptar_hubt(payload: Any) -> Any:
    if not isinstance(payload, dict) or not isinstance(payload.get("modules"), list):
        return payload

    tipos = _tipos_hubt(payload.get("moduleTypes"))
    produtos = []
    for modulo in payload.get("modules") or []:
        if not isinstance(modulo, dict):
            continue
        tipo_id = str(modulo.get("_moduleType") or modulo.get("moduleTypeId") or modulo.get("moduleType") or "")
        tipo_nome = tipos.get(tipo_id, "")
        if tipo_id != "3" and tipo_nome.strip().lower() != "produtos":
            continue

        props = modulo.get("properties") if isinstance(modulo.get("properties"), dict) else {}
        categoria = str(
            props.get("title")
            or modulo.get("title")
            or modulo.get("name")
            or ""
        ).strip()

        for item in modulo.get("items") or []:
            if not isinstance(item, dict):
                continue
            nome = str(item.get("title") or item.get("name") or "").strip()
            if not nome:
                continue
            produtos.append({
                "id": item.get("_id") or item.get("id"),
                "name": nome,
                "description": item.get("desc") or item.get("extraDesc") or item.get("description") or "",
                "price": _preco_hubt(item),
                "image": _imagem_hubt(item),
                "category": categoria,
            })
    return {"products": produtos} if produtos else payload


def _firestore_value(value: Any) -> Any:
    """Converte o formato tipado da API REST do Firestore para Python simples."""
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
    if "geoPointValue" in value:
        gp = value.get("geoPointValue") or {}
        return {"latitude": gp.get("latitude"), "longitude": gp.get("longitude")}
    if "arrayValue" in value:
        vals = (value.get("arrayValue") or {}).get("values") or []
        return [_firestore_value(v) for v in vals]
    if "mapValue" in value:
        fields = (value.get("mapValue") or {}).get("fields") or {}
        return {str(k): _firestore_value(v) for k, v in fields.items()}
    # Estrutura já parcialmente decodificada: preserva recursivamente.
    return {str(k): _firestore_value(v) for k, v in value.items()}


def adaptar_firestore_lojamenu(payload: Any) -> Any:
    """Decodifica respostas documents:runQuery usadas pelo Loja.Menu.

    Não presume onde ficam os produtos. Apenas remove os wrappers tipados do
    Firestore para que o detector genérico consiga enxergar nome/preço/imagem e
    estruturas de personalizações normalmente.
    """
    if not isinstance(payload, list):
        return payload
    documentos = []
    for row in payload:
        if not isinstance(row, dict):
            continue
        doc = row.get("document")
        if not isinstance(doc, dict):
            continue
        fields = doc.get("fields")
        if not isinstance(fields, dict):
            continue
        decoded = {str(k): _firestore_value(v) for k, v in fields.items()}
        decoded["_firestore_document"] = doc.get("name") or ""
        documentos.append(decoded)
    if not documentos:
        return payload
    return {"documents": documentos}


def adaptar_payload(fonte: str, payload: Any) -> Tuple[Any, str]:
    f = (fonte or "").lower()
    if "neemo.com.br" in f and "/menu" in f and "/menu_settings" not in f:
        adaptado = adaptar_neemo(payload)
        if adaptado is not payload:
            return adaptado, "adaptador-neemo"
    if "hassets" in f or "storage.googleapis.com" in f:
        adaptado = adaptar_hubt(payload)
        if adaptado is not payload:
            return adaptado, "adaptador-hubt"
    if "firestore.googleapis.com" in f and "webcatalogo-1" in f and "documents:runquery" in f:
        adaptado = adaptar_firestore_lojamenu(payload)
        if adaptado is not payload:
            return adaptado, "adaptador-loja-menu-firestore"
    return payload, ""
