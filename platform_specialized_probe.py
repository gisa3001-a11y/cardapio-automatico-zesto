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
        consumidos = set()
        if isinstance(value.get("document"), dict):
            doc = value.get("document")
            consumidos.add("document")
        elif isinstance(value.get("documentChange"), dict) and isinstance(value["documentChange"].get("document"), dict):
            doc = value["documentChange"].get("document")
            consumidos.add("documentChange")
        if isinstance(doc, dict) and isinstance(doc.get("fields"), dict):
            dec = {str(k): _firestore_value(v) for k, v in doc["fields"].items()}
            dec["_firestore_document"] = doc.get("name") or ""
            out.append(dec)
        for k, v in value.items():
            if k in consumidos:
                continue
            if isinstance(v, (dict, list)):
                _coletar_documentos_firestore(v, out, depth + 1)
    elif isinstance(value, list):
        for v in value[:1000]:
            if isinstance(v, (dict, list)):
                _coletar_documentos_firestore(v, out, depth + 1)


def probe_lojamenu_firestore(url: str, timeout_ms: int = 35000) -> List[Tuple[str, Any]]:
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


def _probe_dom_precos(url: str, label: str, min_items: int = 5, timeout_ms: int = 30000) -> List[Tuple[str, Any]]:
    """Extrai cards visiveis com nome+preco, com filtros fortes contra UI/carrinho."""
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return []
    produtos = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(
                locale="pt-BR",
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/151 Safari/537.36",
                viewport={"width": 1440, "height": 1200},
            )
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            try:
                page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass
            page.wait_for_timeout(1800)
            try:
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(900)
            except Exception:
                pass
            produtos = page.evaluate(
                """
                () => {
                  const money = /R\\$\\s*([0-9]{1,5}(?:[.,][0-9]{2})?)/i;
                  const bad = /^(?:total|subtotal|frete|taxa(?: de)? entrega|carrinho|checkout|pedido|entrega|retirada|cupom|desconto|finalizar|continuar|buscar|pesquisar|entrar|login)$/i;
                  const selectors = [
                    '[class*="product" i]','[class*="produto" i]','[class*="item" i]',
                    '[class*="card" i]','article','li','mat-card','ion-card'
                  ];
                  const all = Array.from(document.querySelectorAll(selectors.join(','))).slice(0, 5000);
                  const out = [], seen = new Set();
                  for (const el of all) {
                    const style = getComputedStyle(el), rect = el.getBoundingClientRect();
                    if (style.display === 'none' || style.visibility === 'hidden' || rect.width < 70 || rect.height < 24) continue;
                    const text = (el.innerText || '').replace(/\\u00a0/g,' ').trim();
                    if (!text || text.length > 900) continue;
                    const pm = text.match(money); if (!pm) continue;
                    const price = Number(pm[1].replace('.', '').replace(',', '.'));
                    if (!Number.isFinite(price) || price <= 0 || price > 5000) continue;
                    const preferred = el.querySelector('h1,h2,h3,h4,h5,h6,[class*="name" i],[class*="nome" i],[class*="title" i],[class*="titulo" i]');
                    let name = preferred ? (preferred.innerText || '').replace(/\\s+/g,' ').trim() : '';
                    if (!name) {
                      const lines = (el.innerText || '').split(/\\n+/).map(x=>x.replace(/\\s+/g,' ').trim()).filter(Boolean);
                      name = lines.find(x => !money.test(x) && x.length >= 3 && x.length <= 160 && !bad.test(x)) || '';
                    }
                    name = name.replace(/R\\$.*$/i,'').trim();
                    if (!name || name.length < 3 || name.length > 160 || bad.test(name)) continue;
                    const key = name.toLowerCase() + '|' + price.toFixed(2);
                    if (seen.has(key)) continue;
                    let image = '';
                    const img = el.querySelector('img');
                    if (img) image = img.currentSrc || img.src || '';
                    if (image && !/^https?:\\/\\//i.test(image)) image = '';
                    let category = '';
                    const section = el.closest('section,[class*="category" i],[class*="categoria" i],[class*="section" i],[class*="secao" i]');
                    if (section) {
                      const h = section.querySelector('h1,h2,h3,h4,[class*="category" i],[class*="categoria" i]');
                      if (h && h !== el) category = (h.innerText || '').replace(/\\s+/g,' ').trim().slice(0,160);
                    }
                    seen.add(key);
                    out.push({name, price, image, category});
                    if (out.length >= 350) break;
                  }
                  return out;
                }
                """
            )
            browser.close()
    except Exception:
        return []
    if not isinstance(produtos, list) or len(produtos) < min_items:
        return []
    return [(f"specialized:{label}-dom", {"products": produtos})]


def probe_rapidfood_dom(url: str, timeout_ms: int = 30000) -> List[Tuple[str, Any]]:
    if "rapidfood.com.br" not in (url or "").lower():
        return []
    return _probe_dom_precos(url, "rapidfood", 5, timeout_ms)


def probe_especializado(url: str, timeout_ms: int = 35000) -> List[Tuple[str, Any]]:
    low = (url or "").lower()
    if "loja.menu" in low:
        return probe_lojamenu_firestore(url, timeout_ms)
    if "rapidfood.com.br" in low:
        return probe_rapidfood_dom(url, timeout_ms)
    if "saipos.com" in low:
        try:
            from saipos_public_probe import probe_saipos_publico
            api = probe_saipos_publico(url, timeout=max(10, int(timeout_ms / 1000)))
            if api:
                return api
        except Exception:
            pass
        return _probe_dom_precos(url, "saipos", 5, timeout_ms)
    if "menudino.com" in low:
        return _probe_dom_precos(url, "menudino", 5, timeout_ms)
    if "ola.click" in low:
        return _probe_dom_precos(url, "ola-click", 5, timeout_ms)
    if "atlasautomacao.app.br" in low:
        return _probe_dom_precos(url, "atlas", 5, timeout_ms)
    return []
