"""Mapa de rede temporario para casos pendentes do Leitor Universal V2.

Registra somente metadados de requisicoes publicas carregadas pela pagina:
URL, metodo, tipo, status e, no Firestore, nome da colecao/consulta. Nao salva
corpo completo de cardapio, cookies, cabecalhos de autenticacao ou dados privados.
Tambem registra metadados estruturais do DOM (tags/classes/contagens), sem
persistir textos dos produtos, para diagnosticar paginas server-rendered.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import parse_qs, urlparse

CASOS = [
    ("RapidFood", "https://rapidfood.com.br/panelamineira"),
    ("Atlas Automacao", "https://atlasautomacao.app.br/confeitariaandressamarquespds"),
    ("MenuDino", "https://pollolokoouroverde.menudino.com/"),
    ("Ola Click", "https://tatys-burger-2.ola.click/products"),
    ("Saipos", "https://temperodaleia.saipos.com/"),
    ("Loja.Menu", "https://loja.menu/bombuque"),
]

PALAVRAS = (
    "api", "menu", "cardap", "product", "produto", "item", "categoria", "category",
    "catalog", "loja", "store", "merchant", "firestore", "query", "saipos",
)


def _where_summary(node: Any, out: List[Dict[str, Any]] | None = None):
    if out is None:
        out = []
    if len(out) >= 30:
        return out
    if isinstance(node, dict):
        ff = node.get("fieldFilter")
        if isinstance(ff, dict):
            field = ((ff.get("field") or {}).get("fieldPath") if isinstance(ff.get("field"), dict) else None)
            op = ff.get("op")
            value = ff.get("value") if isinstance(ff.get("value"), dict) else {}
            tipo = next((k for k in ("stringValue", "integerValue", "booleanValue", "doubleValue", "nullValue", "referenceValue") if k in value), None)
            out.append({"field": field, "op": op, "value_type": tipo})
        for v in node.values():
            if isinstance(v, (dict, list)):
                _where_summary(v, out)
    elif isinstance(node, list):
        for v in node:
            if isinstance(v, (dict, list)):
                _where_summary(v, out)
    return out


def _query_summary(data: Any) -> Dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    sq = data.get("structuredQuery") if isinstance(data.get("structuredQuery"), dict) else None
    if sq is None:
        target = data.get("target") if isinstance(data.get("target"), dict) else {}
        query = target.get("query") if isinstance(target.get("query"), dict) else {}
        sq = query.get("structuredQuery") if isinstance(query.get("structuredQuery"), dict) else None
    if sq is None:
        add = data.get("addTarget") if isinstance(data.get("addTarget"), dict) else {}
        query = add.get("query") if isinstance(add.get("query"), dict) else {}
        sq = query.get("structuredQuery") if isinstance(query.get("structuredQuery"), dict) else None
    if not isinstance(sq, dict):
        return {}
    out: Dict[str, Any] = {}
    colecoes = []
    for frm in sq.get("from") or []:
        if isinstance(frm, dict) and frm.get("collectionId"):
            colecoes.append(str(frm.get("collectionId")))
    if colecoes:
        out["collections"] = colecoes
    wh = _where_summary(sq.get("where"))
    if wh:
        out["where"] = wh
    if sq.get("limit") is not None:
        out["limit"] = sq.get("limit")
    order = []
    for ob in sq.get("orderBy") or []:
        if isinstance(ob, dict):
            field = ((ob.get("field") or {}).get("fieldPath") if isinstance(ob.get("field"), dict) else None)
            order.append({"field": field, "direction": ob.get("direction")})
    if order:
        out["order_by"] = order
    return out


def _json_candidates_from_form(post_data: str) -> List[Any]:
    out: List[Any] = []
    try:
        form = parse_qs(post_data, keep_blank_values=True)
    except Exception:
        return out
    for values in form.values():
        for raw in values:
            s = (raw or "").strip()
            if not s or s[0] not in "[{":
                continue
            try:
                obj = json.loads(s)
            except Exception:
                continue
            out.append(obj)
            if isinstance(obj, list):
                for item in obj:
                    if isinstance(item, (dict, list)):
                        out.append(item)
    return out


def _walk_query_summaries(node: Any, out: List[Dict[str, Any]] | None = None):
    if out is None:
        out = []
    if len(out) >= 20:
        return out
    if isinstance(node, dict):
        s = _query_summary(node)
        if s and s not in out:
            out.append(s)
        for v in node.values():
            if isinstance(v, (dict, list)):
                _walk_query_summaries(v, out)
    elif isinstance(node, list):
        for v in node:
            if isinstance(v, (dict, list)):
                _walk_query_summaries(v, out)
    return out


def _resumo_post(url: str, post_data: str) -> Dict[str, Any]:
    if not post_data:
        return {}
    try:
        data = json.loads(post_data)
    except Exception:
        out: Dict[str, Any] = {"post_json": False, "post_len": len(post_data)}
        if "firestore.googleapis.com" in url:
            summaries: List[Dict[str, Any]] = []
            for obj in _json_candidates_from_form(post_data):
                _walk_query_summaries(obj, summaries)
            if summaries:
                out["firestore_queries"] = summaries
        return out
    out: Dict[str, Any] = {"post_json": True}
    if "firestore.googleapis.com" in url:
        summaries: List[Dict[str, Any]] = []
        _walk_query_summaries(data, summaries)
        if summaries:
            out["firestore_queries"] = summaries
            if len(summaries) == 1:
                out.update(summaries[0])
    return out


def _relevante(url: str, resource_type: str) -> bool:
    low = (url or "").lower()
    if resource_type in ("xhr", "fetch"):
        return True
    return any(p in low for p in PALAVRAS)


def main():
    from playwright.sync_api import sync_playwright

    saida = []
    with sync_playwright() as p:
        for nome, url in CASOS:
            print(f"[network-map] {nome}", flush=True)
            rows: List[Dict[str, Any]] = []
            seen = set()
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(locale="pt-BR", viewport={"width": 1440, "height": 1200})

            def on_response(resp):
                try:
                    req = resp.request
                    rt = (req.resource_type or "").lower()
                    if not _relevante(resp.url, rt):
                        return
                    post_data = req.post_data or ""
                    key = (resp.url, req.method, post_data)
                    if key in seen or len(rows) >= 400:
                        return
                    seen.add(key)
                    parsed = urlparse(resp.url)
                    row = {
                        "url": resp.url,
                        "host": parsed.netloc,
                        "path": parsed.path,
                        "method": req.method,
                        "resource_type": rt,
                        "status": resp.status,
                        "content_type": (resp.headers.get("content-type") or "").split(";")[0],
                    }
                    row.update(_resumo_post(resp.url, post_data))
                    rows.append(row)
                except Exception:
                    pass

            page.on("response", on_response)
            erro = ""
            final_url = url
            dom = {}
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=40000)
                try:
                    page.wait_for_load_state("networkidle", timeout=12000)
                except Exception:
                    pass
                for frac in (0.25, 0.5, 0.75, 1.0):
                    try:
                        page.evaluate(f"window.scrollTo(0, document.body.scrollHeight * {frac})")
                        page.wait_for_timeout(900)
                    except Exception:
                        pass
                final_url = page.url
                try:
                    dom = page.evaluate(r"""
                    () => {
                      const body = (document.body?.innerText || '').replace(/\s+/g,' ').trim();
                      const links = Array.from(document.querySelectorAll('a[href]')).map(a => a.href).filter(Boolean);
                      const headings = {};
                      for (const tag of ['h1','h2','h3','h4','h5','h6']) headings[tag] = document.querySelectorAll(tag).length;
                      const moneyNodes = Array.from(document.querySelectorAll('body *')).filter(el => {
                        if (el.children.length) return false;
                        return /R\$\s*[0-9]/i.test((el.textContent || '').trim());
                      }).slice(0,80);
                      const moneyStructure = moneyNodes.map(el => {
                        const chain = [];
                        let cur = el;
                        for (let i=0; cur && i<5; i++, cur=cur.parentElement) {
                          chain.push({
                            tag: (cur.tagName || '').toLowerCase(),
                            cls: String(cur.className || '').split(/\s+/).filter(Boolean).slice(0,6),
                            role: cur.getAttribute ? (cur.getAttribute('role') || '') : '',
                            has_button: !!(cur.querySelector && cur.querySelector('button,a')),
                            has_img: !!(cur.querySelector && cur.querySelector('img')),
                            heading_count: cur.querySelectorAll ? cur.querySelectorAll('h1,h2,h3,h4,h5,h6').length : 0,
                          });
                        }
                        return chain;
                      });
                      return {
                        title: document.title || '',
                        text_len: body.length,
                        money_mentions: (body.match(/R\$/g) || []).length,
                        product_word_mentions: (body.match(/produto|product|card[aá]pio|menu/gi) || []).length,
                        links_relevantes: links.filter(x => /menu|produto|product|cardap|pedido|catalog/i.test(x)).slice(0,80),
                        headings,
                        money_leaf_nodes: moneyNodes.length,
                        money_structure: moneyStructure,
                        article_count: document.querySelectorAll('article').length,
                        section_count: document.querySelectorAll('section').length,
                        button_count: document.querySelectorAll('button').length,
                      };
                    }
                    """)
                except Exception:
                    dom = {}
            except Exception as exc:
                erro = str(exc)
            browser.close()
            saida.append({"caso": nome, "url": url, "url_final": final_url, "erro": erro, "dom": dom, "requests": rows})

    Path("artifacts").mkdir(exist_ok=True)
    Path("artifacts/network_map.json").write_text(json.dumps(saida, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
