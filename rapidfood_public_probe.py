"""Leitura publica e conservadora do RapidFood para o Leitor Universal V2.

Tenta primeiro os objetos openProductModal(...) presentes no HTML. Como a
pagina publica tambem entrega nome, preco e categoria no HTML renderizado pelo
servidor, existe um segundo caminho deterministico por headings/price. Se o
servidor nao entregar os cards completos, o navegador repete a mesma leitura
semantica no DOM renderizado. Nao gera XLSX.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Tuple

import requests
from bs4 import BeautifulSoup, Tag

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/151 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

MONEY_RE = re.compile(r"R\$\s*([0-9]{1,5}(?:[.,][0-9]{2})?)", re.I)
BAD_TITLES = {
    "cart", "carrinho", "categories", "categorias", "store info", "informacoes da loja",
    "my addresses", "meus enderecos", "order history", "historico de pedidos",
    "sign in", "entrar", "any notes?", "observacoes", "total",
}


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


def extrair_open_product_modal(html: str) -> List[Dict[str, Any]]:
    """Extrai somente objetos JSON validos passados a openProductModal."""
    soup = BeautifulSoup(html or "", "html.parser")
    produtos: List[Dict[str, Any]] = []
    vistos = set()
    for el in soup.select("[onclick*='openProductModal']"):
        onclick = el.get("onclick") or ""
        m = re.search(r"openProductModal\((\{.*\})\)", onclick, re.S)
        if not m:
            continue
        try:
            obj = json.loads(m.group(1))
        except Exception:
            continue
        pid = str(obj.get("id") or "")
        nome = str(obj.get("nome") or obj.get("name") or "").strip()
        if not pid or not nome or pid in vistos:
            continue
        vistos.add(pid)
        produtos.append(obj)
    return produtos


def _normalizar(produtos: List[Dict[str, Any]]) -> Dict[str, Any]:
    out = []
    for obj in produtos:
        preco_raw = obj.get("preco_display")
        if preco_raw in (None, ""):
            preco_raw = obj.get("preco")
        imagem = obj.get("imagem_url") or obj.get("imagem") or obj.get("image") or ""
        if imagem and not str(imagem).startswith(("http://", "https://")):
            imagem = ""
        out.append({
            "id": str(obj.get("id") or ""),
            "name": str(obj.get("nome") or obj.get("name") or "").strip(),
            "description": str(obj.get("descricao") or obj.get("description") or "").strip(),
            "category": str(obj.get("categoria_nome") or obj.get("categoria") or obj.get("category") or "").strip(),
            "image": str(imagem),
            "price": _to_float(preco_raw),
        })
    return {"products": out}


def _texto_limpo(tag: Tag | None) -> str:
    if tag is None:
        return ""
    return " ".join(tag.get_text(" ", strip=True).split())


def extrair_cards_semanticos_html(html: str) -> List[Dict[str, Any]]:
    """Extrai produtos do HTML publico sem depender de classes CSS."""
    soup = BeautifulSoup(html or "", "html.parser")
    produtos: List[Dict[str, Any]] = []
    vistos = set()
    categoria_atual = ""

    for tag in soup.find_all(["h2", "h3"]):
        titulo = _texto_limpo(tag)
        if not titulo:
            continue
        low = titulo.casefold()
        if tag.name == "h2":
            if low not in BAD_TITLES and len(titulo) <= 180:
                categoria_atual = titulo
            continue

        if low in BAD_TITLES or len(titulo) < 2 or len(titulo) > 180:
            continue

        card = tag
        escolhido = None
        for _ in range(8):
            card = card.parent if isinstance(card.parent, Tag) else None
            if card is None:
                break
            texto = _texto_limpo(card)
            if len(texto) > 2200:
                break
            if MONEY_RE.search(texto):
                acao = any(
                    re.search(r"adicionar|add(?: to cart)?|comprar", _texto_limpo(x), re.I)
                    for x in card.find_all(["button", "a"], limit=12)
                )
                if acao or card.find("img") is not None:
                    escolhido = card
                    break
        if escolhido is None:
            continue

        texto = _texto_limpo(escolhido)
        precos = MONEY_RE.findall(texto)
        if not precos:
            continue
        preco = _to_float(precos[0])
        if preco <= 0 or preco > 5000:
            continue

        descricao = ""
        for cand in escolhido.find_all(["p", "span", "div"], limit=30):
            t = _texto_limpo(cand)
            if not t or t == titulo or MONEY_RE.search(t):
                continue
            if re.search(r"adicionar|add(?: to cart)?|promo|mais pedido|most ordered", t, re.I):
                continue
            if 6 <= len(t) <= 600:
                descricao = t
                break

        imagem = ""
        img = escolhido.find("img")
        if img is not None:
            src = img.get("src") or img.get("data-src") or img.get("data-lazy-src") or ""
            if isinstance(src, str) and src.startswith(("http://", "https://")):
                imagem = src

        chave = (titulo.casefold(), round(preco, 2))
        if chave in vistos:
            continue
        vistos.add(chave)
        produtos.append({
            "id": f"rf-html-{len(produtos)+1}",
            "name": titulo,
            "description": descricao,
            "category": categoria_atual,
            "image": imagem,
            "price": preco,
        })

    return produtos


def _probe_cards_renderizados(url: str, timeout: int = 25) -> Dict[str, Any]:
    """Fallback pelo DOM real: h2=categoria, h3=produto, ancestral com preco."""
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return {"products": []}

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(
                locale="pt-BR",
                user_agent=HEADERS["User-Agent"],
                viewport={"width": 1440, "height": 1200},
            )
            page.goto(url, wait_until="domcontentloaded", timeout=max(15000, timeout * 1000))
            try:
                page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass

            for frac in (0.20, 0.40, 0.60, 0.80, 1.00):
                try:
                    page.evaluate(f"window.scrollTo(0, Math.max(document.body.scrollHeight, document.documentElement.scrollHeight) * {frac})")
                    page.wait_for_timeout(450)
                except Exception:
                    pass
            page.wait_for_timeout(900)

            produtos = page.evaluate(
                r"""
                () => {
                  const money = /R\$\s*([0-9]{1,5}(?:[.,][0-9]{2})?)/i;
                  const bad = new Set([
                    'cart','carrinho','categories','categorias','store info','informacoes da loja',
                    'my addresses','meus enderecos','order history','historico de pedidos',
                    'sign in','entrar','any notes?','observacoes','total'
                  ]);
                  const clean = s => (s || '').replace(/\u00a0/g,' ').replace(/\s+/g,' ').trim();
                  const headings = Array.from(document.querySelectorAll('h2,h3'));
                  const out = [], seen = new Set();
                  let category = '';
                  let seq = 1;

                  for (const h of headings) {
                    const title = clean(h.innerText);
                    if (!title) continue;
                    const low = title.toLowerCase();
                    if (h.tagName === 'H2') {
                      if (!bad.has(low) && title.length <= 180) category = title;
                      continue;
                    }
                    if (bad.has(low) || title.length < 2 || title.length > 180) continue;

                    let card = h;
                    let chosen = null;
                    for (let depth = 0; depth < 10 && card; depth++, card = card.parentElement) {
                      const txt = clean(card.innerText);
                      if (!txt) continue;
                      if (txt.length > 2600) break;
                      if (!money.test(txt)) continue;
                      const hasAction = Array.from(card.querySelectorAll('button,a')).slice(0,16)
                        .some(x => /adicionar|add(?: to cart)?|comprar/i.test(clean(x.innerText)));
                      const hasImage = !!card.querySelector('img');
                      if (hasAction || hasImage) { chosen = card; break; }
                    }
                    if (!chosen) continue;

                    const txt = clean(chosen.innerText);
                    const matches = Array.from(txt.matchAll(/R\$\s*([0-9]{1,5}(?:[.,][0-9]{2})?)/ig));
                    if (!matches.length) continue;
                    const raw = matches[0][1];
                    const price = Number(raw.replace(/\./g,'').replace(',','.'));
                    if (!Number.isFinite(price) || price <= 0 || price > 5000) continue;

                    const key = low + '|' + price.toFixed(2);
                    if (seen.has(key)) continue;
                    seen.add(key);

                    let description = '';
                    const lines = (chosen.innerText || '').split(/\n+/).map(clean).filter(Boolean);
                    for (const line of lines) {
                      if (line === title || money.test(line)) continue;
                      if (/^(?:promo|featured|most ordered|mais pedido|adicionar|add(?: to cart)?|comprar)$/i.test(line)) continue;
                      if (line.length >= 6 && line.length <= 600) { description = line; break; }
                    }

                    let image = '';
                    const img = chosen.querySelector('img');
                    if (img) {
                      const src = img.currentSrc || img.src || '';
                      if (/^https?:\/\//i.test(src)) image = src;
                    }
                    out.push({id:'rf-dom-'+(seq++), name:title, description, category, image, price});
                    if (out.length >= 250) break;
                  }
                  return out;
                }
                """
            )
            browser.close()
    except Exception:
        return {"products": []}

    if not isinstance(produtos, list):
        return {"products": []}
    return {"products": produtos}


def probe_rapidfood_publico(url: str, timeout: int = 25) -> List[Tuple[str, Any]]:
    if "rapidfood.com.br" not in (url or "").lower():
        return []

    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
        r.raise_for_status()
        html = r.text

        produtos = extrair_open_product_modal(html)
        if produtos:
            payload = _normalizar(produtos)
            if len(payload.get("products") or []) >= 3:
                return [("specialized:rapidfood-openProductModal", payload)]

        semanticos = extrair_cards_semanticos_html(html)
        if len(semanticos) >= 5:
            return [("specialized:rapidfood-semantic-html", {"products": semanticos})]
    except Exception:
        pass

    payload = _probe_cards_renderizados(url, timeout=timeout)
    if len(payload.get("products") or []) >= 5:
        return [("specialized:rapidfood-semantic-dom", payload)]
    return []
