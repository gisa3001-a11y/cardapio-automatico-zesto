"""Probes especializados e conservadores para excecoes da V2.

Objetivo: destravar plataformas que exibem o cardapio publicamente, mas nao
entregam um JSON simples ao detector generico. Nenhuma rotina gera XLSX.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Tuple


MONEY_RE = re.compile(r"R\$\s*([0-9]{1,4}(?:[.,][0-9]{2})?)", re.I)


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


def _json_frames(texto: str) -> List[Any]:
    """Extrai JSONs de respostas WebChannel com prefixos de tamanho/controle."""
    texto = (texto or "").strip()
    if not texto or len(texto) > 12_000_000:
        return []
    candidatos: List[Any] = []
    decoder = json.JSONDecoder()
    i = 0
    while i < len(texto) and len(candidatos) < 160:
        if texto[i] not in "[{":
            i += 1
            continue
        try:
            obj, end = decoder.raw_decode(texto, i)
            candidatos.append(obj)
            i = max(end, i + 1)
        except Exception:
            i += 1
    return candidatos


def _coletar_documentos_firestore(value: Any, out: List[Dict[str, Any]], depth: int = 0):
    if depth > 15 or len(out) >= 600:
        return
    if isinstance(value, dict):
        doc = None
        if isinstance(value.get("document"), dict):
            doc = value.get("document")
        elif isinstance(value.get("documentChange"), dict) and isinstance(value["documentChange"].get("document"), dict):
            doc = value["documentChange"].get("document")
        if isinstance(doc, dict) and isinstance(doc.get("fields"), dict):
            dec = {str(k): _firestore_value(v) for k, v in doc["fields"].items()}
            dec["_firestore_document"] = doc.get("name") or ""
            out.append(dec)
        for v in value.values():
            if isinstance(v, (dict, list)):
                _coletar_documentos_firestore(v, out, depth + 1)
    elif isinstance(value, list):
        for v in value[:1000]:
            if isinstance(v, (dict, list)):
                _coletar_documentos_firestore(v, out, depth + 1)


def probe_lojamenu_firestore(url: str, timeout_ms: int = 35000) -> List[Tuple[str, Any]]:
    """Observa somente respostas publicas do Firestore carregadas pelo Loja.Menu."""
    if "loja.menu" not in (url or "").lower():
        return []
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return []

    documentos: List[Dict[str, Any]] = []
    vistos = set()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(locale="pt-BR", viewport={"width": 1440, "height": 1200})

            def on_response(resp):
                try:
                    low = resp.url.lower()
                    if "firestore.googleapis.com" not in low or resp.status < 200 or resp.status >= 300:
                        return
                    texto = resp.text()
                    for frame in _json_frames(texto):
                        achados: List[Dict[str, Any]] = []
                        _coletar_documentos_firestore(frame, achados)
                        for doc in achados:
                            chave = doc.get("_firestore_document") or json.dumps(doc, sort_keys=True, ensure_ascii=False)[:500]
                            if chave in vistos:
                                continue
                            vistos.add(chave)
                            documentos.append(doc)
                except Exception:
                    pass

            page.on("response", on_response)
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            try:
                page.wait_for_load_state("networkidle", timeout=12000)
            except Exception:
                pass
            page.wait_for_timeout(2500)
            browser.close()
    except Exception:
        return []

    return [("specialized:loja-menu-firestore-listen", {"documents": documentos})] if documentos else []


def probe_rapidfood_dom(url: str, timeout_ms: int = 30000) -> List[Tuple[str, Any]]:
    """Le cards server-renderizados do RapidFood sem clicar nem enviar dados."""
    if "rapidfood.com.br" not in (url or "").lower():
        return []
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return []

    produtos = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(locale="pt-BR", viewport={"width": 1440, "height": 1200})
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            page.wait_for_timeout(1200)
            produtos = page.evaluate(
                """
                () => {
                  const money = /R\\$\\s*([0-9]{1,4}(?:[.,][0-9]{2})?)/i;
                  const bad = /^(?:total|subtotal|frete|taxa|carrinho|checkout|pedido|entrega|retirada)$/i;
                  const all = Array.from(document.querySelectorAll('body *')).slice(0, 9000);
                  const out = [], seen = new Set();
                  for (const el of all) {
                    if (el.children.length > 14) continue;
                    const text = (el.innerText || '').trim();
                    if (!text || text.length > 550 || !money.test(text)) continue;
                    const rect = el.getBoundingClientRect();
                    if (rect.width < 80 || rect.height < 25) continue;
                    const lines = (el.innerText || '').split(/\\n+/).map(x => x.replace(/\\s+/g,' ').trim()).filter(Boolean);
                    if (lines.length < 2 || lines.length > 12) continue;
                    const pm = text.match(money); if (!pm) continue;
                    const price = Number(pm[1].replace('.', '').replace(',', '.'));
                    if (!Number.isFinite(price) || price <= 0 || price > 5000) continue;
                    let name = lines.find(x => !money.test(x) && x.length >= 3 && x.length <= 140 && !bad.test(x)) || '';
                    if (!name) continue;
                    name = name.replace(/\\s+/g,' ').trim();
                    const key = name.toLowerCase() + '|' + price.toFixed(2);
                    if (seen.has(key)) continue;
                    const img = el.querySelector('img');
                    let image = img ? (img.currentSrc || img.src || '') : '';
                    if (image && !/^https?:\\/\\//i.test(image)) image = '';
                    seen.add(key); out.push({name, price, image, category:''});
                    if (out.length >= 250) break;
                  }
                  return out;
                }
                """
            )
            browser.close()
    except Exception:
        return []

    # O cardapio de teste conhecido exibe dezenas de precos; exigir 5 reduz falsos positivos.
    return [("specialized:rapidfood-dom", {"products": produtos})] if isinstance(produtos, list) and len(produtos) >= 5 else []


def probe_especializado(url: str, timeout_ms: int = 35000) -> List[Tuple[str, Any]]:
    low = (url or "").lower()
    if "loja.menu" in low:
        return probe_lojamenu_firestore(url, timeout_ms)
    if "rapidfood.com.br" in low:
        return probe_rapidfood_dom(url, timeout_ms)
    return []
