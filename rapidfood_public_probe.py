"""Leitura publica e conservadora do RapidFood para o Leitor Universal V2.

Ordem:
1. openProductModal no HTML;
2. headings + preco no HTML;
3. HTML final renderizado pelo Chromium;
4. fallback DOM simples.

Nao gera XLSX.
"""
from __future__ import annotations

import json
import re
import shutil
from typing import Any, Dict, List, Tuple

import requests
from bs4 import BeautifulSoup, Tag

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/151 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.7",
}

MONEY_RE = re.compile(r"R\$\s*([0-9]{1,5}(?:[.,][0-9]{2})?)", re.I)
BAD_TITLES = {
    "cart", "carrinho", "categories", "categorias", "store info", "informacoes da loja",
    "my addresses", "meus enderecos", "order history", "historico de pedidos",
    "sign in", "entrar", "any notes?", "observacoes", "total", "profile", "perfil",
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


def _texto_limpo(tag: Tag | None) -> str:
    if tag is None:
        return ""
    return " ".join(tag.get_text(" ", strip=True).split())


def extrair_open_product_modal(html: str) -> List[Dict[str, Any]]:
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


def _imagem_no_bloco(tag: Tag) -> str:
    img = tag.find("img")
    if img is None:
        return ""
    src = img.get("src") or img.get("data-src") or img.get("data-lazy-src") or ""
    return src if isinstance(src, str) and src.startswith(("http://", "https://")) else ""


def _produto_por_ancestral(tag: Tag, titulo: str, categoria: str):
    card: Tag | None = tag
    for _ in range(10):
        card = card.parent if card is not None and isinstance(card.parent, Tag) else None
        if card is None:
            break
        texto = _texto_limpo(card)
        if len(texto) > 2600:
            break
        precos = MONEY_RE.findall(texto)
        if not precos:
            continue
        preco = _to_float(precos[0])
        if preco <= 0 or preco > 5000:
            continue
        acao = any(
            re.search(r"adicionar|add(?: to cart)?|comprar", _texto_limpo(x), re.I)
            for x in card.find_all(["button", "a"], limit=16)
        )
        imagem = _imagem_no_bloco(card)
        if not acao and not imagem:
            continue
        descricao = ""
        for cand in card.find_all(["p", "span", "div"], limit=40):
            t = _texto_limpo(cand)
            if not t or t == titulo or MONEY_RE.search(t):
                continue
            if re.search(r"adicionar|add(?: to cart)?|promo|mais pedido|most ordered", t, re.I):
                continue
            if 6 <= len(t) <= 650:
                descricao = t
                break
        return {
            "name": titulo,
            "description": descricao,
            "category": categoria,
            "image": imagem,
            "price": preco,
        }
    return None


def _produto_por_fluxo(tag: Tag, titulo: str, categoria: str):
    """Le o trecho entre este h3 e o proximo h2/h3.

    Funciona mesmo quando preco/botao/imagem nao compartilham um ancestral pequeno.
    """
    textos: List[str] = []
    imagem = ""
    encontrou_acao = False
    for el in tag.find_all_next(limit=45):
        if el is tag:
            continue
        if isinstance(el, Tag) and el.name in ("h2", "h3"):
            break
        if not isinstance(el, Tag):
            continue
        if not imagem and el.name == "img":
            src = el.get("src") or el.get("data-src") or el.get("data-lazy-src") or ""
            if isinstance(src, str) and src.startswith(("http://", "https://")):
                imagem = src
        t = _texto_limpo(el)
        if not t:
            continue
        if el.name in ("button", "a") and re.search(r"adicionar|add(?: to cart)?|comprar", t, re.I):
            encontrou_acao = True
        if len(t) <= 900:
            textos.append(t)
    bloco = " ".join(textos)
    m = MONEY_RE.search(bloco)
    if not m:
        return None
    preco = _to_float(m.group(1))
    if preco <= 0 or preco > 5000:
        return None
    if not encontrou_acao and not imagem:
        return None
    descricao = ""
    for t in textos:
        if t == titulo or MONEY_RE.search(t) or re.search(r"adicionar|add(?: to cart)?|comprar|promo|most ordered", t, re.I):
            continue
        if 6 <= len(t) <= 650:
            descricao = t
            break
    return {
        "name": titulo,
        "description": descricao,
        "category": categoria,
        "image": imagem,
        "price": preco,
    }


def extrair_cards_semanticos_html(html: str) -> List[Dict[str, Any]]:
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

        item = _produto_por_ancestral(tag, titulo, categoria_atual)
        if item is None:
            item = _produto_por_fluxo(tag, titulo, categoria_atual)
        elif not item.get("image"):
            # No RapidFood real, texto/preco/botao podem estar em um bloco interno
            # enquanto a foto fica como irmao logo depois. O ancestral pequeno e
            # correto para preco/nome, mas perde essa foto. Complementamos somente
            # quando o fluxo encontra a MESMA faixa de produto e o MESMO preco.
            fluxo = _produto_por_fluxo(tag, titulo, categoria_atual)
            if (
                fluxo
                and fluxo.get("image")
                and round(float(fluxo.get("price") or 0), 2) == round(float(item.get("price") or 0), 2)
            ):
                item["image"] = fluxo["image"]
        if item is None:
            continue

        chave = (titulo.casefold(), round(float(item["price"]), 2))
        if chave in vistos:
            continue
        vistos.add(chave)
        item["id"] = f"rf-html-{len(produtos)+1}"
        produtos.append(item)
    return produtos


def _probe_cards_renderizados(url: str, timeout: int = 25) -> Dict[str, Any]:
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return {"products": []}

    try:
        with sync_playwright() as p:
            chromium_sistema = (
                shutil.which("chromium")
                or shutil.which("chromium-browser")
                or shutil.which("google-chrome")
                or shutil.which("google-chrome-stable")
            )

            launch_kwargs = {
                "headless": True,
                "args": ["--no-sandbox", "--disable-dev-shm-usage"],
            }
            if chromium_sistema:
                launch_kwargs["executable_path"] = chromium_sistema

            browser = p.chromium.launch(**launch_kwargs)
            # IMPORTANTE: manter o user-agent nativo do Chromium. O diagnostico real
            # abre o RapidFood dessa forma; forcar um UA Windows sobre Chromium Linux
            # gera client-hints inconsistentes e a pagina pode entregar DOM diferente.
            page = browser.new_page(
                locale="pt-BR",
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
                    page.wait_for_timeout(500)
                except Exception:
                    pass
            page.wait_for_timeout(900)

            try:
                html_renderizado = page.content()
                semanticos = extrair_cards_semanticos_html(html_renderizado)
            except Exception:
                semanticos = []
            if len(semanticos) >= 5:
                browser.close()
                return {"products": semanticos}

            produtos = page.evaluate(r"""
            () => {
              const money = /R\$\s*([0-9]{1,5}(?:[.,][0-9]{2})?)/i;
              const bad = /^(?:cart|carrinho|categories|categorias|store info|sign in|entrar|total|any notes\?)$/i;
              const out = [], seen = new Set();
              let categoria = '';
              for (const el of document.querySelectorAll('h2,h3')) {
                const title = (el.innerText || '').replace(/\s+/g,' ').trim();
                if (!title) continue;
                if (el.tagName === 'H2') { if (!bad.test(title)) categoria = title; continue; }
                if (bad.test(title)) continue;
                let card = el, found = null;
                for (let i=0; i<12 && card; i++, card=card.parentElement) {
                  const text=(card.innerText||'').trim();
                  if (text.length<=2600 && money.test(text)) { found=card; break; }
                }
                if (!found) continue;
                const text=(found.innerText||'').trim();
                const m=text.match(money); if (!m) continue;
                const price=Number(m[1].replace(/\./g,'').replace(',','.'));
                if (!Number.isFinite(price) || price<=0 || price>5000) continue;
                const key=title.toLowerCase()+'|'+price.toFixed(2); if (seen.has(key)) continue;
                seen.add(key);
                const img=found.querySelector('img');
                out.push({id:'rf-dom-'+(out.length+1),name:title,price,category:categoria,image:img?(img.currentSrc||img.src||''):''});
              }
              return out;
            }
            """)
            browser.close()
    except Exception:
        return {"products": []}

    return {"products": produtos if isinstance(produtos, list) else []}


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
        return [("specialized:rapidfood-rendered-html", payload)]
    return []
