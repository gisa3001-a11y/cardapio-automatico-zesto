"""Leitura publica e conservadora do RapidFood para o Leitor Universal V2.

Tenta primeiro os objetos openProductModal(...) presentes no HTML. Quando a
plataforma entrega os cards somente depois da renderizacao, usa um fallback
Playwright dirigido por imagens de produtos + preco visivel. Nao gera XLSX.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Tuple

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/151 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
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


def _probe_cards_renderizados(url: str, timeout: int = 25) -> Dict[str, Any]:
    """Fallback dirigido ao DOM real da RapidFood.

    O mapa de rede confirma fotos em /dashboard/uploads/produtos/. A plataforma
    pode usa-las tanto em <img> quanto em background-image; por isso o probe
    considera os dois formatos e faz scroll progressivo antes de coletar cards.
    """
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

            # Carrega cards lazy sem depender de um unico salto para o rodape.
            for frac in (0.20, 0.40, 0.60, 0.80, 1.00):
                try:
                    page.evaluate(f"window.scrollTo(0, Math.max(document.body.scrollHeight, document.documentElement.scrollHeight) * {frac})")
                    page.wait_for_timeout(450)
                except Exception:
                    pass
            page.wait_for_timeout(900)

            produtos = page.evaluate(
                """
                () => {
                  const money = /R\$\s*([0-9]{1,5}(?:[.,][0-9]{2})?)/i;
                  const isProductUrl = s => {
                    s = (s || '').toLowerCase();
                    return s.includes('/dashboard/uploads/produtos/') || s.includes('/uploads/produtos/');
                  };
                  const imageUrl = el => {
                    if (!el) return '';
                    if (el.tagName === 'IMG') {
                      const s = el.currentSrc || el.src || '';
                      return isProductUrl(s) ? s : '';
                    }
                    const bg = getComputedStyle(el).backgroundImage || '';
                    const m = bg.match(/url\(["']?([^"')]+)["']?\)/i);
                    return m && isProductUrl(m[1]) ? m[1] : '';
                  };

                  const anchors = [];
                  for (const el of Array.from(document.querySelectorAll('img,[style],div,span,a,button'))) {
                    const src = imageUrl(el);
                    if (src) anchors.push({el, src});
                    if (anchors.length >= 500) break;
                  }

                  const out = [], seen = new Set();
                  let seq = 1;
                  const badName = /^(?:adicionar|comprar|ver mais|detalhes|indisponivel|esgotado|carrinho|pedido)$/i;

                  for (const anchor of anchors) {
                    let card = anchor.el;
                    let escolhido = null;
                    for (let i = 0; i < 11 && card; i++, card = card.parentElement) {
                      const txt = (card.innerText || '').replace(/\u00a0/g, ' ').trim();
                      if (txt && txt.length <= 1800 && money.test(txt)) {
                        escolhido = card;
                        break;
                      }
                    }
                    if (!escolhido) continue;

                    const text = (escolhido.innerText || '').replace(/\u00a0/g, ' ').trim();
                    const prices = Array.from(text.matchAll(/R\$\s*([0-9]{1,5}(?:[.,][0-9]{2})?)/ig));
                    if (!prices.length) continue;
                    const raw = prices[prices.length - 1][1];
                    const price = Number(raw.replace(/\./g, '').replace(',', '.'));
                    if (!Number.isFinite(price) || price <= 0 || price > 5000) continue;

                    const titleEl = escolhido.querySelector('h1,h2,h3,h4,h5,h6,[class*="name" i],[class*="nome" i],[class*="title" i],[class*="titulo" i]');
                    let name = titleEl ? (titleEl.innerText || '').replace(/\s+/g, ' ').trim() : '';
                    if (!name || money.test(name) || badName.test(name)) {
                      const lines = text.split(/\n+/).map(x => x.replace(/\s+/g, ' ').trim()).filter(Boolean);
                      name = lines.find(x => !money.test(x) && x.length >= 3 && x.length <= 160 && !badName.test(x)) || '';
                    }
                    name = name.replace(/R\$.*$/i, '').trim();
                    if (!name || name.length < 3 || name.length > 160 || badName.test(name)) continue;

                    const key = name.toLowerCase() + '|' + price.toFixed(2);
                    if (seen.has(key)) continue;
                    seen.add(key);

                    let category = '';
                    let section = escolhido.closest('section,[class*="category" i],[class*="categoria" i],[class*="section" i],[class*="secao" i]');
                    if (section) {
                      const h = section.querySelector('h1,h2,h3,h4,h5,h6');
                      const t = h ? (h.innerText || '').replace(/\s+/g, ' ').trim() : '';
                      if (t && !money.test(t) && t.length <= 120 && t.toLowerCase() !== name.toLowerCase()) category = t;
                    }

                    out.push({id: 'rf-dom-' + (seq++), name, price, image: anchor.src, category});
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

    # 1) caminho mais barato/deterministico: HTML puro.
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
        r.raise_for_status()
        produtos = extrair_open_product_modal(r.text)
        if produtos:
            payload = _normalizar(produtos)
            if len(payload.get("products") or []) >= 3:
                return [("specialized:rapidfood-openProductModal", payload)]
    except Exception:
        pass

    # 2) pagina atual pode montar os cards apenas apos renderizacao.
    payload = _probe_cards_renderizados(url, timeout=timeout)
    if len(payload.get("products") or []) >= 5:
        return [("specialized:rapidfood-product-images-dom", payload)]
    return []
