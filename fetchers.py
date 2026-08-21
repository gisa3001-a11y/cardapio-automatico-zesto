import json
import re
import requests
from datetime import datetime
from bs4 import BeautifulSoup
from urllib.parse import urlparse
from models import Produto, GrupoOpcao, Resultado
from utils import texto_seguro, parse_preco, imagem_compativel, tipo_grupo, parece_pizza, parece_combo

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/151 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json;q=0.8,*/*;q=0.7",
}

def get(url, **kwargs):
    h = dict(HEADERS)
    h.update(kwargs.pop("headers", {}) or {})
    r = requests.get(url, headers=h, timeout=30, allow_redirects=True, **kwargs)
    r.raise_for_status()
    return r

def detectar_plataforma(url):
    u = url.lower()
    if "anota.ai" in u:
        return "Anota AI"
    if "rapidfood" in u:
        return "RapidFood"
    if "byfood" in u:
        return "byFood"
    if "instadelivery.com.br" in u:
        return "InstaDelivery"
    if "brendi.com.br" in u:
        return "Brendi"
    if "ola.click" in u:
        return "Ola Click"
    if "cardapioweb.com" in u:
        return "Cardápio Web"
    if "saipos.com" in u:
        return "Saipos"
    if "menudino.com" in u:
        return "MenuDino"
    if "menuintegrado.com.br" in u or "menui.com.br" in u:
        return "Menui / Menu Integrado"
    if "meucomercio.com.br" in u:
        return "MeuComércio"
    return None



# ============================================================
# FINAL CORRIGIDA — helpers de materialização
# ============================================================

def _diag_candidato(diag, url_contem=None, tipo_inline=None, score_min=0):
    """Retorna o melhor payload já capturado pelo diagnóstico universal."""
    candidatos = (diag or {}).get("ranking_json") or []
    for c in candidatos:
        if not isinstance(c, dict):
            continue
        if (c.get("score_v17") if c.get("score_v17") is not None else c.get("score", 0)) < score_min:
            continue
        url = str(c.get("url") or "")
        if url_contem and url_contem not in url:
            continue
        if tipo_inline and url != f"inline-script:{tipo_inline}":
            continue
        if c.get("data") is not None:
            return c.get("data"), url
    return None, None


def _capturar_resposta_json_playwright(url, trecho_url):
    """
    Captura uma resposta JSON pública durante o carregamento da página.
    Corrige a função ausente que quebrava Anota AI.
    """
    from playwright.sync_api import sync_playwright

    capturado = {"data": None, "url": None}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            locale="pt-BR",
            user_agent=HEADERS["User-Agent"],
            viewport={"width": 1440, "height": 1200},
        )

        def on_response(resp):
            if capturado["data"] is not None:
                return
            try:
                if trecho_url not in resp.url:
                    return
                if resp.status < 200 or resp.status >= 300:
                    return
                capturado["data"] = resp.json()
                capturado["url"] = resp.url
            except Exception:
                pass

        page.on("response", on_response)
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3500)
        browser.close()

    if capturado["data"] is None:
        raise ValueError(f"Nenhuma resposta JSON correspondente a {trecho_url!r} foi capturada.")
    return capturado["data"], capturado["url"]


def _materializar_grupos_genericos(res, obj, prefixo="gen"):
    """
    Converte grupos comuns de options/modifiers/add-ons para GrupoOpcao.
    Corrige a função ausente que quebrava Ola Click e também serve de fallback.
    """
    if not isinstance(obj, dict):
        return []

    group_keys = (
        "option_groups", "optionGroups", "options_groups",
        "modifier_groups", "modifierGroups", "modifiers",
        "complement_groups", "complementGroups", "complements",
        "add_ons", "addons", "extras", "variations"
    )
    option_keys = (
        "options", "items", "choices", "itens", "subitems",
        "complements", "modifiers", "values"
    )

    grupos = []
    vistos_g = set()

    raw_groups = []
    for k in group_keys:
        v = obj.get(k)
        if isinstance(v, list):
            raw_groups.extend(v)

    for gi, g in enumerate(raw_groups):
        if not isinstance(g, dict) or not _ativo_generico(g):
            continue

        opts = []
        for k in option_keys:
            v = g.get(k)
            if isinstance(v, list):
                opts = v
                break
        if not opts:
            continue

        gid = str(_primeiro(g, "id", "_id", "uuid", "group_id", default=f"{prefixo}-{gi+1}"))
        if gid in vistos_g:
            continue

        gnome = texto_seguro(_primeiro(g, "name", "title", "nome", "label", default="Adicionais"))
        try:
            minimo = int(float(_primeiro(g, "min", "minimum", "min_choices", "minimum_quantity", default=0) or 0))
        except Exception:
            minimo = 0
        try:
            maximo = int(float(_primeiro(g, "max", "maximum", "max_choices", "maximum_quantity", default=1) or 1))
        except Exception:
            maximo = 1
        if maximo <= 0:
            maximo = max(1, len(opts))

        validos = []
        for oi, o in enumerate(opts):
            if not isinstance(o, dict) or not _ativo_generico(o):
                continue
            onome = texto_seguro(_primeiro(o, "name", "title", "nome", "label", "description", default=""))
            if not onome:
                continue
            preco = parse_preco(_primeiro(
                o, "price", "additional_price", "additionalPrice",
                "extra_price", "extraPrice", "aditional_price", "value", default=0
            ))
            validos.append(GrupoOpcao(
                grupo_id=gid,
                tipo=tipo_grupo(gnome),
                grupo_nome=gnome,
                nome=onome,
                imagem=imagem_compativel(_primeiro(o, "image", "image_url", "imageUrl", "photo", default="")),
                preco=preco,
                minimo=minimo,
                maximo=maximo,
                repetir=1 if bool(_primeiro(o, "allow_repeat", "repeat", "permite_multiplo", default=False)) else 0,
                metodo_preco=1,
            ))

        if validos:
            vistos_g.add(gid)
            grupos.append(gid)
            ja = {str(x.grupo_id) for x in res.grupos}
            if gid not in ja:
                res.grupos.extend(validos)

    return grupos


# ----------------------------
# Menui / Menu Integrado
# ----------------------------

def _parse_menuintegrado_categories(data):
    """Converte diretamente /internal/categories?channel=platform."""
    if not isinstance(data, list):
        raise ValueError("Menui: payload de categorias inválido.")

    res = Resultado(origem="Menui / Menu Integrado FINAL CORRIGIDA / internal/categories")
    grupos_escritos = set()
    produtos_vistos = set()

    for cat in data:
        if not isinstance(cat, dict):
            continue
        if cat.get("forceAlwaysVisible") is False and cat.get("alwaysAvailable") is False:
            continue
        categoria = texto_seguro(cat.get("name") or "")

        for p in cat.get("products") or []:
            if not isinstance(p, dict):
                continue
            if p.get("inStock") is False and p.get("showWhenUnavailable") is False:
                continue

            pid = str(p.get("id") or p.get("uuid") or p.get("code") or "")
            if pid and pid in produtos_vistos:
                continue
            if pid:
                produtos_vistos.add(pid)

            nome = texto_seguro(p.get("name") or "")
            if not nome:
                continue
            desc = texto_seguro(p.get("description") or "")
            preco = parse_preco(p.get("price"))

            # Quando o preço-base é 0, usa o menor preço positivo das variações.
            # Isso evita produto R$0,00 quando a plataforma exibe "A partir de".
            variations = p.get("variations") or []
            if preco <= 0:
                precos_base = []
                for g in variations:
                    for o in (g.get("items") or []) if isinstance(g, dict) else []:
                        if isinstance(o, dict) and o.get("inStock") is not False:
                            pr = parse_preco(o.get("price"))
                            if pr > 0:
                                precos_base.append(pr)
                if precos_base:
                    preco = min(precos_base)

            gids = []
            for gi, g in enumerate(variations):
                if not isinstance(g, dict):
                    continue
                opts = [o for o in (g.get("items") or []) if isinstance(o, dict) and o.get("inStock") is not False]
                if not opts:
                    continue
                gid = f"menui-{g.get('id') or g.get('uuid') or pid+'-'+str(gi+1)}"
                gnome = texto_seguro(g.get("name") or "Adicionais")
                minimo = int(g.get("min") or 0)
                maximo = int(g.get("max") or 1)
                if maximo <= 0:
                    maximo = max(1, len(opts))
                gids.append(gid)

                if gid not in grupos_escritos:
                    validos = []
                    for o in opts:
                        onome = texto_seguro(o.get("name") or "")
                        if not onome:
                            continue
                        validos.append(GrupoOpcao(
                            grupo_id=gid,
                            tipo=tipo_grupo(gnome),
                            grupo_nome=gnome,
                            nome=onome,
                            imagem=imagem_compativel(o.get("coverImageUrl") or ""),
                            preco=parse_preco(o.get("price")),
                            minimo=minimo,
                            maximo=maximo,
                            repetir=0,
                            # reducer pode ser summing, higher/largest etc.
                            metodo_preco=3 if "maior" in str(g.get("hint") or "").lower() else 1,
                        ))
                    if validos:
                        res.grupos.extend(validos)
                        grupos_escritos.add(gid)

            prod = Produto(
                codigo=pid or str(len(res.itens)+len(res.pizzas)+1),
                nome=nome,
                descricao=desc,
                categoria=categoria,
                imagem=imagem_compativel(p.get("coverImageUrl") or ""),
                preco=preco,
                grupos=gids,
                pizza=parece_pizza(nome, categoria, desc),
                combo=parece_combo(nome, categoria, desc),
            )
            (res.pizzas if prod.pizza and not prod.combo else res.itens).append(prod)

    _dedupe_result(res)
    return res


# ----------------------------
# Saipos
# ----------------------------

def _parse_saipos_view_data(data):
    """
    Converte /v1/stores/{id}/sales/view-data.
    Choices ficam separados dos items e são ligados por id_store_choice.
    """
    if not isinstance(data, dict):
        raise ValueError("Saipos: view-data inválido.")

    res = Resultado(origem="Saipos FINAL CORRIGIDA / sales/view-data")
    choices_map = {}
    grupos_escritos = set()

    for g in data.get("choices") or []:
        if isinstance(g, dict) and g.get("id_store_choice") is not None:
            choices_map[str(g.get("id_store_choice"))] = g

    for item in data.get("items") or []:
        if not isinstance(item, dict):
            continue

        cat = item.get("category_item") or {}
        # Categorias explicitamente desabilitadas não entram.
        if isinstance(cat, dict) and str(cat.get("enabled") or "Y").upper() == "N":
            continue

        nome = texto_seguro(item.get("desc_store_item") or "")
        if not nome:
            continue
        desc = texto_seguro(item.get("detail") or item.get("desc_store_item_delivery") or "")
        categoria = texto_seguro(cat.get("desc_store_category_item") or "") if isinstance(cat, dict) else ""

        # preço da variação habilitada; promoções não substituem sem necessidade.
        preco = 0.0
        for v in item.get("variations") or []:
            if not isinstance(v, dict) or str(v.get("enabled") or "Y").upper() == "N":
                continue
            preco = parse_preco(v.get("price"))
            if preco >= 0:
                break

        gids = []
        for link in item.get("choices") or []:
            if not isinstance(link, dict):
                continue
            raw_gid = link.get("id_store_choice")
            if raw_gid is None:
                continue
            g = choices_map.get(str(raw_gid))
            if not isinstance(g, dict):
                continue

            opts = []
            for o in g.get("choice_items") or []:
                if not isinstance(o, dict) or str(o.get("enabled") or "Y").upper() == "N":
                    continue
                onome = texto_seguro(o.get("desc_store_choice_item") or "")
                if not onome:
                    continue
                adicional = 0.0
                for vv in o.get("variations") or []:
                    if isinstance(vv, dict) and vv.get("aditional_price") is not None:
                        adicional = parse_preco(vv.get("aditional_price"))
                        break
                opts.append((onome, adicional, o.get("img_path") or ""))

            if not opts:
                continue

            gid = f"saipos-{raw_gid}"
            gids.append(gid)
            if gid in grupos_escritos:
                continue

            gnome = texto_seguro(g.get("desc_store_choice") or "Adicionais")
            minimo = int(g.get("min_choices") or 0)
            maximo = int(g.get("max_choices") or 1)
            if maximo <= 0:
                maximo = max(1, len(opts))

            for onome, adicional, img in opts:
                res.grupos.append(GrupoOpcao(
                    grupo_id=gid,
                    tipo=tipo_grupo(gnome),
                    grupo_nome=gnome,
                    nome=onome,
                    imagem=imagem_compativel(img),
                    preco=adicional,
                    minimo=minimo,
                    maximo=maximo,
                    repetir=0,
                    metodo_preco=1,
                ))
            grupos_escritos.add(gid)

        prod = Produto(
            codigo=str(item.get("id_store_item") or len(res.itens)+1),
            nome=nome,
            descricao=desc,
            categoria=categoria,
            imagem=imagem_compativel(item.get("img_path") or ""),
            preco=preco,
            grupos=gids,
            pizza=parece_pizza(nome, categoria, desc),
            combo=parece_combo(nome, categoria, desc),
        )
        (res.pizzas if prod.pizza and not prod.combo else res.itens).append(prod)

    _dedupe_result(res)
    return res


# ----------------------------
# MeuComércio
# ----------------------------

def _parse_meucomercio_next_data(data):
    """Converte productsData do __NEXT_DATA__, preservando categoria e preço promocional final."""
    try:
        pd = data["props"]["pageProps"]["productsData"]
    except Exception:
        raise ValueError("MeuComércio: __NEXT_DATA__ sem productsData.")

    produtos = []
    if isinstance(pd.get("products"), dict):
        produtos.extend(pd["products"].get("list") or [])
    produtos.extend(pd.get("promoProducts") or [])

    res = Resultado(origem="MeuComércio FINAL CORRIGIDA / __NEXT_DATA__")
    vistos = set()

    for p in produtos:
        if not isinstance(p, dict):
            continue
        pid = str(p.get("ProductId") or p.get("ProductCode") or "")
        nome = texto_seguro(p.get("ProductName") or "")
        if not nome:
            continue
        chave = pid or nome.lower()
        if chave in vistos:
            continue
        vistos.add(chave)

        preco = parse_preco(p.get("SalePrice"))
        if p.get("PromoActive") and parse_preco(p.get("PromoSalePrice")) > 0:
            preco = parse_preco(p.get("PromoSalePrice"))

        photos = p.get("Photos") or []
        img = ""
        if photos and isinstance(photos[0], dict):
            img = photos[0].get("url") or ""
        if not img and p.get("ProductImg"):
            img = str(p.get("ProductImg"))

        categoria = texto_seguro(p.get("Category") or "")
        desc = texto_seguro(p.get("ProductDescr") or "")

        prod = Produto(
            codigo=pid or str(len(res.itens)+1),
            nome=nome,
            descricao=desc,
            categoria=categoria,
            imagem=imagem_compativel(img),
            preco=preco,
            grupos=[],
            pizza=parece_pizza(nome, categoria, desc),
            combo=bool(p.get("Combo")) or parece_combo(nome, categoria, desc),
        )
        (res.pizzas if prod.pizza and not prod.combo else res.itens).append(prod)

    _dedupe_result(res)
    return res


# ----------------------------
# Ola Click / Nuxt devalue
# ----------------------------

def _nuxt_devalue_decode(root):
    """
    Decodifica a tabela de referências usada por __NUXT_DATA__.
    Implementação suficiente para os estados Pinia observados no Ola Click.
    """
    if not isinstance(root, list):
        return root

    memo = {}
    resolving = set()
    tags = {"Reactive", "ShallowReactive", "Ref", "ShallowRef", "Readonly", "ShallowReadonly"}

    def ref(v):
        if isinstance(v, int) and not isinstance(v, bool) and 0 <= v < len(root):
            return resolve(v)
        if isinstance(v, (dict, list)):
            return node(v)
        return v

    def resolve(i):
        if i in memo:
            return memo[i]
        if i in resolving:
            return None
        resolving.add(i)
        out = node(root[i])
        memo[i] = out
        resolving.remove(i)
        return out

    def node(v):
        if isinstance(v, list):
            if len(v) == 2 and isinstance(v[0], str) and v[0] in tags:
                return ref(v[1])
            if v and v[0] == "Set":
                return [ref(x) for x in v[1:]]
            # EmptyRef é metadado do devalue/Nuxt; não é dado de cardápio.
            if len(v) == 2 and v[0] == "EmptyRef":
                return None
            return [ref(x) for x in v]
        if isinstance(v, dict):
            return {k: ref(x) for k, x in v.items()}
        return v

    return resolve(0)


def _parse_olaclick_nuxt_data(raw):
    decoded = _nuxt_devalue_decode(raw)
    try:
        store = decoded["pinia"]["productsCategories"]
        cats = store.get("productsCategories") or store.get("originalProductsCategories") or []
    except Exception:
        raise ValueError("Ola Click: productsCategories não encontrado no __NUXT_DATA__.")

    res = Resultado(origem="Ola Click FINAL CORRIGIDA / __NUXT_DATA__")
    vistos = set()

    for cat in cats:
        if not isinstance(cat, dict) or cat.get("visible") is False:
            continue
        # 'Destaques' duplica itens de categorias reais; deixa a categoria real prevalecer.
        if str(cat.get("type") or "").upper() == "FAVORITE":
            continue
        categoria = texto_seguro(cat.get("name") or "")

        for p in cat.get("products") or []:
            if not isinstance(p, dict) or p.get("visible") is False:
                continue
            pid = str(p.get("id") or "")
            if pid and pid in vistos:
                continue
            if pid:
                vistos.add(pid)

            nome = texto_seguro(p.get("name") or "")
            if not nome:
                continue
            desc = texto_seguro(p.get("description") or "")
            variants = p.get("product_variants") or []
            preco = 0.0
            for v in variants:
                if isinstance(v, dict):
                    preco = parse_preco(v.get("price"))
                    if preco >= 0:
                        break

            imgs = p.get("images") or []
            img = ""
            if imgs and isinstance(imgs[0], dict):
                img = imgs[0].get("image_url") or ""

            prod = Produto(
                codigo=pid or str(len(res.itens)+1),
                nome=nome,
                descricao=desc,
                categoria=categoria,
                imagem=imagem_compativel(img),
                preco=preco,
                grupos=[],
                pizza=parece_pizza(nome, categoria, desc),
                combo=parece_combo(nome, categoria, desc),
            )
            (res.pizzas if prod.pizza and not prod.combo else res.itens).append(prod)

    _dedupe_result(res)
    return res



def _primeiro(d, *keys, default=None):
    if not isinstance(d, dict):
        return default
    for k in keys:
        if k in d and d.get(k) not in (None, ""):
            return d.get(k)
    return default

def _lista(v):
    return v if isinstance(v, list) else []

def _ativo_generico(obj):
    if not isinstance(obj, dict):
        return False
    if obj.get("out") is True:
        return False
    status = str(obj.get("status") or "").upper()
    if status in {"INACTIVE", "DISABLED", "HIDDEN", "DELETED", "UNAVAILABLE"}:
        return False
    for k in ("active", "enabled", "available", "visible", "published", "is_active", "isActive"):
        if k in obj and obj.get(k) is False:
            return False
    return True

def _grupo_opcoes_generico(g):
    if not isinstance(g, dict):
        return []
    for k in (
        "choices", "options", "items", "itens", "subitems", "complements",
        "modifiers", "values", "children"
    ):
        v = g.get(k)
        if isinstance(v, list) and v:
            return v
    return []


def _resultado_melhor_que(a, b):
    """Compara resultados sem depender de uma única métrica."""
    if a is None:
        return False
    if b is None:
        return True
    qa = (
        len(a.itens) + len(a.pizzas),
        len({str(g.grupo_id) for g in a.grupos}),
        len(a.grupos),
        sum(len(p.grupos or []) for p in (a.itens + a.pizzas)),
    )
    qb = (
        len(b.itens) + len(b.pizzas),
        len({str(g.grupo_id) for g in b.grupos}),
        len(b.grupos),
        sum(len(p.grupos or []) for p in (b.itens + b.pizzas)),
    )
    return qa > qb


def _extrair_html_dom_oficial(url, plataforma):
    """
    FINAL: fonte HTML/DOM oficial para RapidFood/byFood e outros casos
    sem JSON operacional.
    """
    html = render_playwright(url)

    if plataforma == "byFood":
        # Reutiliza o parser específico byFood sobre o HTML estático/renderizado.
        res = buscar_byfood(url)
        if len(res.itens) + len(res.pizzas) >= 3:
            return res
        gen = interpretar_html(html, origem="byFood FINAL / DOM oficial")
        gen = limpar_resultado_generico(gen, "byFood")
        return gen

    if plataforma == "RapidFood":
        res = interpretar_html(html, origem="RapidFood FINAL / DOM oficial")
        res = limpar_resultado_generico(res, "RapidFood")
        return res

    res = interpretar_html(html, origem=f"{plataforma} FINAL / DOM oficial")
    res = limpar_resultado_generico(res, plataforma)
    return res


def _extrair_por_fonte_final(url, plataforma, diag):
    """
    FINAL CORRIGIDA:
    usa as fontes já comprovadas pelo diagnóstico.
    Zesto deliberadamente não faz parte do escopo.
    """

    if plataforma == "Anota AI":
        # Primeiro aproveita a própria resposta já capturada pelo diagnóstico.
        data, endpoint = _diag_candidato(diag, url_contem="clientauth/nm-category/menu-merchant", score_min=10)
        if data is not None:
            res = _parse_anota_ai_payload(data)
            res.origem = "Anota AI FINAL CORRIGIDA / diagnóstico API"
            return res
        return buscar_anota_ai(url)

    if plataforma == "InstaDelivery":
        return buscar_instadelivery(url)

    if plataforma == "Menui / Menu Integrado":
        data, endpoint = _diag_candidato(diag, url_contem="/internal/categories?channel=platform", score_min=10)
        if data is not None:
            return _parse_menuintegrado_categories(data)
        return buscar_menui(url)

    if plataforma == "Saipos":
        data, endpoint = _diag_candidato(diag, url_contem="/sales/view-data", score_min=9)
        if data is not None:
            return _parse_saipos_view_data(data)
        return _extrair_html_dom_oficial(url, plataforma)

    if plataforma == "MeuComércio":
        data, endpoint = _diag_candidato(diag, tipo_inline="__next_data__", score_min=9)
        if data is not None:
            return _parse_meucomercio_next_data(data)
        return _extrair_html_dom_oficial(url, plataforma)

    if plataforma == "Ola Click":
        data, endpoint = _diag_candidato(diag, tipo_inline="__nuxt_data__", score_min=10)
        if data is not None:
            return _parse_olaclick_nuxt_data(data)
        return buscar_olaclick(url)

    if plataforma == "Brendi":
        return buscar_brendi(url)

    if plataforma == "Cardápio Web":
        return buscar_cardapioweb(url)

    if plataforma == "RapidFood":
        # Importante: NÃO retorna mais o DOM genérico antes de tentar a API de opções.
        return buscar_rapidfood(url)

    if plataforma == "byFood":
        return buscar_byfood(url)

    return _extrair_html_dom_oficial(url, plataforma or "Fallback")



def _rapidfood_categorias_por_dom(url, res):
    """FINAL: recupera categorias pela ordem visual do DOM da RapidFood."""
    try:
        html = render_playwright(url)
        soup = BeautifulSoup(html, "html.parser")
        mapa = {}
        categoria = ""
        # A página pública organiza o cardápio por headings.
        for el in soup.find_all(["h2","h3"]):
            nome = re.sub(r"\s+", " ", el.get_text(" ", strip=True)).strip()
            if not nome:
                continue
            if el.name == "h2":
                if nome.lower() not in ("categorias","categories","carrinho","cart"):
                    categoria = texto_seguro(nome)
                continue
            # h3 = produto; associa ao último h2.
            if categoria:
                mapa[nome.lower()] = categoria

        for p in (res.itens + res.pizzas):
            if not p.categoria:
                cat = mapa.get((p.nome or "").strip().lower())
                if cat:
                    p.categoria = cat
        return len([p for p in (res.itens+res.pizzas) if p.categoria])
    except Exception as e:
        res.avisos.append(f"FINAL: categorias RapidFood não puderam ser enriquecidas: {e}")
        return 0


def _diagnostico_final_detalhe(url, plataforma, max_produtos=8):
    """
    Última tentativa dirigida para RapidFood/byFood.
    Inspeciona controles reais de detalhe (radio/checkbox/select),
    atributos onclick/data-* e rede após clique.
    """
    from playwright.sync_api import sync_playwright
    out = {
        "versao":"FINAL",
        "tipo":"diagnostico_final_detalhe",
        "plataforma":plataforma,
        "url":url,
        "produtos_testados":0,
        "detalhes":[],
        "conclusao":"sem_evidencia_de_adicionais",
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            locale="pt-BR",
            viewport={"width":1440,"height":1200},
            user_agent=HEADERS["User-Agent"],
        )
        network = []

        def on_resp(resp):
            try:
                typ = resp.request.resource_type
                ct = (resp.headers.get("content-type") or "").lower()
                if typ not in ("xhr","fetch") and "json" not in ct:
                    return
                low = resp.url.lower()
                if any(x in low for x in ("analytics","facebook","google","clarity","sentry")):
                    return
                rec = {"url":resp.url,"status":resp.status,"type":typ,"content_type":ct}
                try:
                    raw = resp.body()
                    if len(raw) < 1500000:
                        s = raw.decode("utf-8", errors="replace")
                        if re.search(r"(adicion|complement|modifier|option|extra|sabor|topping|min|max)", s, re.I):
                            rec["preview"] = s[:20000]
                except Exception:
                    pass
                network.append(rec)
            except Exception:
                pass

        page.on("response", on_resp)
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(1800)

        # coleta pistas estáticas
        static = page.evaluate("""() => {
          const els=[...document.querySelectorAll('[onclick],[data-product-id],[data-produto-id],[data-id]')];
          return els.slice(0,300).map(e=>({
            tag:e.tagName, text:(e.innerText||'').trim().slice(0,300),
            onclick:e.getAttribute('onclick'),
            productId:e.getAttribute('data-product-id'),
            produtoId:e.getAttribute('data-produto-id'),
            id:e.getAttribute('data-id')
          })).filter(x=>x.onclick||x.productId||x.produtoId);
        }""")
        out["pistas_estaticas"] = static[:100]

        selectors = (
            ["[onclick*='openProductModal']", "[onclick*='produto']", "[data-product-id]", ".product", ".produto"]
            if plataforma == "RapidFood" else
            ["[data-produto-id]", "[data-product-id]", "[onclick*='produto']", "[onclick*='product']",
             "img[src*='/produtos/']", "img[data-src*='/produtos/']"]
        )

        candidates=[]
        seen=set()
        for sel in selectors:
            try:
                loc=page.locator(sel)
                for i in range(min(loc.count(),100)):
                    el=loc.nth(i)
                    try:
                        if el.evaluate("(e)=>e.tagName.toLowerCase()")=="img":
                            anc=el.locator("xpath=ancestor::*[self::button or self::a or @onclick or @data-product-id or @data-produto-id][1]")
                            if anc.count(): el=anc.first
                        sig=el.evaluate("(e)=>(e.outerHTML||'').slice(0,1000)")
                        if sig in seen: continue
                        seen.add(sig)
                        txt=(el.inner_text(timeout=1000) or "").strip()
                        if txt or "img" in sig.lower():
                            candidates.append(el)
                    except Exception:
                        pass
            except Exception:
                pass

        for idx,el in enumerate(candidates[:max_produtos]):
            before=len(network)
            d={"indice":idx+1,"card":"","controles":[],"rede":[],"texto_detalhe":"","erro":None}
            try:
                try: d["card"]=re.sub(r"\s+"," ",el.inner_text(timeout=1000) or "")[:500]
                except: pass
                el.scroll_into_view_if_needed(timeout=2500)
                try: el.click(timeout=3500)
                except: el.evaluate("(e)=>e.click()")
                page.wait_for_timeout(900)

                # controles visíveis são a evidência mais forte de adicionais
                controls = page.locator("input[type=radio]:visible,input[type=checkbox]:visible,select:visible")
                for j in range(min(controls.count(),100)):
                    c=controls.nth(j)
                    try:
                        d["controles"].append(c.evaluate("""e=>({
                          type:e.type||e.tagName, name:e.name||'', value:e.value||'',
                          min:e.min||'', max:e.max||'',
                          label:(e.labels&&e.labels[0]?e.labels[0].innerText:'')
                        })"""))
                    except: pass

                # texto do modal/drawer visível
                for sel in ("[role=dialog]:visible",".modal:visible",".offcanvas:visible",".drawer:visible"):
                    try:
                        l=page.locator(sel)
                        if l.count():
                            t=re.sub(r"\s+"," ",l.first.inner_text(timeout=1500) or "")
                            if len(t)>len(d["texto_detalhe"]): d["texto_detalhe"]=t[:5000]
                    except: pass

                d["rede"]=network[before:][:40]
                if d["controles"] or re.search(r"(adicion|complement|opç|extra|sabor|escolha|min|max)", d["texto_detalhe"], re.I):
                    out["conclusao"]="ha_evidencia_de_adicionais_no_detalhe"
            except Exception as e:
                d["erro"]=str(e)
            out["detalhes"].append(d)
            out["produtos_testados"] += 1

            # fecha overlays quando possível
            for s in ("[role=dialog] button[aria-label=Close]:visible",".modal .close:visible",".modal .btn-close:visible",".offcanvas .btn-close:visible"):
                try:
                    l=page.locator(s)
                    if l.count():
                        l.first.click(timeout=800); page.wait_for_timeout(150); break
                except: pass

        browser.close()
    return out



def buscar_por_url(url, usar_playwright=True):
    """
    FINAL:
    - diagnostica primeiro;
    - escolhe a melhor fonte;
    - extrai orientado pela fonte;
    - preserva parsers específicos comprovados.
    """
    plataforma = detectar_plataforma(url)

    diag = None
    if usar_playwright:
        try:
            diag = diagnosticar_rede_universal(
                url,
                plataforma=plataforma or "Desconhecida"
            )
        except Exception:
            diag = None

    try:
        res = _extrair_por_fonte_final(url, plataforma, diag)
    except Exception as exc:
        try:
            setattr(exc, "_plataforma_detectada", plataforma or "Desconhecida")
        except Exception:
            pass
        raise

    # Se o resultado específico vier muito fraco em plataformas HTML/DOM,
    # compara com fallback genérico e mantém o mais rico.
    if usar_playwright and plataforma in ("RapidFood", "byFood"):
        try:
            alt = _extrair_html_dom_oficial(url, plataforma)
            # Nunca troca um resultado que já possui adicionais por um DOM sem adicionais.
            if res.grupos:
                pass
            elif _resultado_melhor_que(alt, res):
                res = alt
        except Exception as alt_exc:
            res.avisos.append(f"FINAL CORRIGIDA: fallback DOM adicional falhou: {alt_exc}")

    if diag is None and usar_playwright:
        try:
            diag = diagnosticar_rede_universal(
                url,
                plataforma=plataforma or "Desconhecida"
            )
        except Exception:
            diag = None

    if plataforma == "RapidFood":
        _rapidfood_categorias_por_dom(url, res)

    if diag is not None:
        if plataforma in ("RapidFood", "byFood"):
            try:
                diag["diagnostico_final_v16"] = _diagnostico_final_detalhe(
                    url, plataforma, max_produtos=8
                )
            except Exception as e:
                diag["diagnostico_final_v16"] = {
                    "versao":"FINAL","tipo":"diagnostico_final_detalhe","erro":str(e)
                }
        # Corrige definitivamente o registro da fonte HTML/DOM.
        if plataforma in ("RapidFood","byFood"):
            dom = diag.get("html_dom") or {}
            if dom.get("score",0) >= 4:
                diag["melhor_fonte"] = {"tipo":"html_dom","candidato":dom}
        diag["parser_origem"] = res.origem
        diag["fonte_oficial_final"] = ((diag.get("melhor_fonte") or {}).get("tipo"))
        diag["resultado_final"] = {
            "regulares": len(res.itens),
            "pizzas": len(res.pizzas),
            "produtos_total": len(res.itens) + len(res.pizzas),
            "opcoes_adicionais": len(res.grupos),
            "grupos_distintos": len({str(g.grupo_id) for g in res.grupos}),
            "vinculos_produto_grupo": sum(len(p.grupos or []) for p in (res.itens + res.pizzas)),
            "produtos_com_categoria": len([p for p in (res.itens + res.pizzas) if p.categoria]),
            "categorias_distintas": len({p.categoria for p in (res.itens + res.pizzas) if p.categoria}),
        }
        setattr(res, "_diagnostico_rede", diag)

    return res




def _parse_anota_ai_payload(data):
    """
    Formato atual do Anota AI:
      data.menu.menu     -> categorias/produtos
      data.menu.menu_aux -> grupos/opções
      produto.next_steps[].category -> vínculo com grupo
    """
    raiz = data.get("data") if isinstance(data, dict) and isinstance(data.get("data"), dict) else data
    menu_obj = raiz.get("menu") if isinstance(raiz, dict) else None

    if isinstance(menu_obj, dict) and isinstance(menu_obj.get("menu"), list):
        cats = menu_obj.get("menu") or []
        aux = menu_obj.get("menu_aux") or []
    else:
        cats = _lista(_primeiro(raiz or {}, "menu", "categories", default=[]))
        aux = _lista(_primeiro(raiz or {}, "menu_aux", "aux", default=[]))

    aux_map = {}
    for g in aux:
        if not isinstance(g, dict):
            continue
        for key in ("_id", "id", "category_id", "category"):
            if g.get(key) not in (None, ""):
                aux_map[str(g.get(key))] = g

    res = Resultado(origem="Anota AI FINAL CORRIGIDA / API")
    grupos_escritos = set()

    def grupo_from_ref(step):
        ref = _primeiro(step, "category", "category_id", "id", "_id", default="")
        g = aux_map.get(str(ref))
        if g is None and _grupo_opcoes_generico(step):
            g = step
        return g

    for cat in cats:
        if not isinstance(cat, dict) or not _ativo_generico(cat):
            continue

        cat_name = texto_seguro(_primeiro(cat, "title", "name", default=""))
        cat_type = str(cat.get("category_type") or "")
        produtos = _lista(_primeiro(cat, "itens", "items", "products", default=[]))

        for p in produtos:
            if not isinstance(p, dict) or not _ativo_generico(p):
                continue

            # Anota AI usa "out" para indisponível.
            if p.get("out") is True:
                continue

            nome = texto_seguro(_primeiro(p, "title", "name", default=""))
            if not nome:
                continue

            desc = texto_seguro(_primeiro(p, "description", "descricao", default=""))
            img = imagem_compativel(_primeiro(p, "image", "cover", "picture", default=""))
            preco = parse_preco(_primeiro(p, "price_base", "price", "value", default=0))
            gids = []

            for step in _lista(_primeiro(p, "next_steps", "nextSteps", default=[])):
                if not isinstance(step, dict):
                    continue
                g = grupo_from_ref(step)
                if not isinstance(g, dict):
                    continue

                gid = str(_primeiro(
                    g, "_id", "id", "category_id", "category",
                    default=_primeiro(step, "category", "_id", "id", default="")
                ))
                if not gid:
                    continue

                gnome = texto_seguro(_primeiro(g, "title", "name", default="Adicionais"))
                minimo = int(_primeiro(
                    step, "min", "minimum",
                    default=_primeiro(g, "min", "minimum", default=0)
                ) or 0)
                maximo = int(_primeiro(
                    step, "max", "maximum",
                    default=_primeiro(g, "max", "maximum", default=1)
                ) or 1)
                price_model = int(_primeiro(step, "price_model", "priceModel", default=0) or 0)

                opts = _lista(_primeiro(g, "itens", "items", "options", "choices", default=[]))
                validos = []
                for o in opts:
                    if not isinstance(o, dict) or not _ativo_generico(o) or o.get("out") is True:
                        continue
                    onome = texto_seguro(_primeiro(o, "title", "name", default=""))
                    if not onome:
                        continue
                    validos.append(GrupoOpcao(
                        grupo_id=gid,
                        tipo=tipo_grupo(gnome),
                        grupo_nome=gnome,
                        nome=onome,
                        imagem=imagem_compativel(_primeiro(o, "image", "cover", "picture", default="")),
                        preco=parse_preco(_primeiro(o, "price_base", "price", "value", default=0)),
                        minimo=minimo,
                        maximo=maximo,
                        repetir=0,
                        metodo_preco=price_model if price_model in (0, 1, 2, 3, 4) else 1,
                    ))

                if validos:
                    gids.append(gid)
                    if gid not in grupos_escritos:
                        res.grupos.extend(validos)
                        grupos_escritos.add(gid)

            pizza = (cat_type.lower() == "pizza") or parece_pizza(nome, cat_name, desc)
            combo = parece_combo(nome, cat_name, desc)
            prod = Produto(
                codigo=str(_primeiro(
                    p, "item_id", "id", "_id", "category_item_id",
                    default=len(res.itens) + len(res.pizzas) + 1
                )),
                nome=nome,
                descricao=desc,
                categoria=cat_name,
                imagem=img,
                preco=preco,
                grupos=list(dict.fromkeys(gids)),
                pizza=bool(pizza and not combo),
                combo=bool(combo),
            )
            (res.pizzas if prod.pizza else res.itens).append(prod)

    _dedupe_result(res)
    return res


def buscar_anota_ai(url):
    m = re.search(r"/loja/([^/?#]+)", url)
    if not m:
        raise ValueError("URL Anota AI inválida.")
    slug = m.group(1)

    # Primeiro tenta o método direto antigo, porque ainda pode funcionar em algumas lojas.
    try:
        token = get(
            f"https://api.anota.ai/client/noauth/access/get-token/{slug}",
            headers={"Accept":"application/json"}
        ).json()
        access = token.get("token") or token.get("access_token") or token.get("data",{}).get("token")
        if access:
            api = "https://api.anota.ai/clientauth/nm-category/menu-merchant?displaySources=DIGITAL_MENU"
            data = get(api, headers={"Authorization": f"Bearer {access}", "Accept":"application/json"}).json()
            res = _parse_anota_ai_payload(data)
            if len(res.itens)+len(res.pizzas):
                res.origem = "Anota AI FINAL / API direta"
                return res
    except Exception:
        pass

    # FINAL: o navegador obtém a autenticação atual e nós observamos somente a resposta pública do menu.
    data, endpoint = _capturar_resposta_json_playwright(
        url,
        "clientauth/nm-category/menu-merchant"
    )
    res = _parse_anota_ai_payload(data)
    res.origem = "Anota AI FINAL / rede Playwright"
    setattr(res, "_endpoint_anota", endpoint)
    if not (res.itens or res.pizzas):
        raise ValueError("Anota AI: a resposta atual do menu foi capturada, mas nenhum produto pôde ser interpretado.")
    return res


def _normalizar_nome_produto(s):
    s = (s or "").lower()
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"[^\w\sáàâãéêíóôõúüç-]", "", s, flags=re.I)
    return s


def _rapidfood_parse_options_payload(data, res, product, grupos_escritos):
    """
    Converte /store/get_product_options.php em GrupoOpcao + vínculos.
    """
    if not isinstance(data, dict) or not data.get("success"):
        return

    for g in data.get("options") or []:
        if not isinstance(g, dict):
            continue

        raw_opts = [o for o in (g.get("opcoes") or []) if isinstance(o, dict)]
        if not raw_opts:
            # Há grupos retornados sem opções; não devem gerar grupo vazio no XLSX.
            continue

        gid = f"rf-{g.get('id')}"
        if gid not in product.grupos:
            product.grupos.append(gid)

        if gid in grupos_escritos:
            continue

        minimo = int(g.get("min_opcoes") or 0)
        maximo = int(g.get("max_opcoes") or 1)
        if maximo <= 0:
            maximo = max(1, len(raw_opts))

        grupo_nome = texto_seguro(g.get("nome") or "Adicionais")
        repetir = 1 if any(int(o.get("permite_multiplo") or 0) == 1 for o in raw_opts) else 0

        validos = []
        for o in raw_opts:
            nome = texto_seguro(o.get("nome") or "")
            if not nome:
                continue
            validos.append(GrupoOpcao(
                grupo_id=gid,
                tipo=tipo_grupo(grupo_nome),
                grupo_nome=grupo_nome,
                nome=nome,
                imagem="",
                preco=parse_preco(o.get("preco")),
                minimo=minimo,
                maximo=maximo,
                repetir=repetir,
                metodo_preco=1,
            ))

        if validos:
            grupos_escritos.add(gid)
            res.grupos.extend(validos)


def _rapidfood_produtos_do_dom(html):
    """
    Extrai o objeto completo passado para openProductModal(...).
    O objeto contém ID, nome, descrição, preço, imagem e categoria.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    encontrados = []
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
        if not pid or pid in vistos:
            continue
        vistos.add(pid)
        encontrados.append(obj)

    return encontrados


def _byfood_titulo_grupo(group_el):
    """
    Localiza o título visual imediatamente anterior ao .ctn-opcoes-item,
    ignorando caixas de pesquisa e textos auxiliares.
    """
    sib = group_el
    for _ in range(10):
        sib = sib.find_previous_sibling()
        if sib is None:
            break
        txt = re.sub(r"\s+", " ", sib.get_text(" ", strip=True)).strip()
        if not txt:
            continue
        low = txt.lower()
        if "pesquisar neste grupo" in low:
            continue
        if len(txt) <= 120:
            return texto_seguro(txt)
    return "Adicionais"


def _byfood_parse_detail_html(detail_html, res, product, grupos_escritos):
    """
    Converte o HTML de /produtos/visualizar/{id} em grupos/opções.
    """
    soup = BeautifulSoup(detail_html or "", "html.parser")
    grupos = soup.select(".ctn-opcoes-item")

    for gi, g in enumerate(grupos):
        minimo = int(g.get("min-quantidade") or 0)
        maximo = int(g.get("max-quantidade") or 0)

        inputs = g.select("input[name*='pedidos_produtos_opcoes']")
        if not inputs:
            continue

        # O ID real do grupo está no primeiro índice de pedidos_produtos_opcoes[GRUPO][OPÇÃO].
        gid_raw = None
        for inp in inputs:
            name = inp.get("name") or ""
            mm = re.search(r"pedidos_produtos_opcoes\[(\d+)\]", name)
            if mm:
                gid_raw = mm.group(1)
                break
        if not gid_raw:
            gid_raw = f"{product.codigo}-{gi+1}"

        gid = f"byf-{gid_raw}"
        grupo_nome = _byfood_titulo_grupo(g)

        # max=0 aparece em grupos radio; nesses casos inferimos 1.
        input_types = {(i.get("type") or "").lower() for i in inputs}
        if maximo <= 0:
            maximo = 1 if ("radio" in input_types) else max(1, len(inputs))

        repetir = 0
        for inp in inputs:
            try:
                if int(inp.get("data-max-qtde") or 0) > 1:
                    repetir = 1
                    break
            except Exception:
                pass

        if gid not in product.grupos:
            product.grupos.append(gid)

        if gid in grupos_escritos:
            continue

        validos = []
        for inp in inputs:
            inp_id = inp.get("id") or ""
            label = soup.find("label", attrs={"for": inp_id}) if inp_id else None
            nome = ""
            if label:
                # Remove texto de preço do label.
                clone = BeautifulSoup(str(label), "html.parser")
                for span in clone.select(".text-currency, .x-currency, small"):
                    span.decompose()
                nome = texto_seguro(re.sub(r"\s+", " ", clone.get_text(" ", strip=True)).strip())

            if not nome:
                nome = texto_seguro(inp.get("value") or "")
            if not nome or nome.isdigit():
                continue

            preco = parse_preco(inp.get("data-price") or 0)

            # imagem opcional no mesmo item
            img = ""
            holder = inp.find_parent(class_=re.compile(r"(form-group|input-radio|input-checkbox)"))
            if holder:
                imgel = holder.find("img")
                if imgel:
                    img = imagem_compativel(imgel.get("src") or imgel.get("data-src") or "")

            validos.append(GrupoOpcao(
                grupo_id=gid,
                tipo=tipo_grupo(grupo_nome),
                grupo_nome=grupo_nome,
                nome=nome,
                imagem=img,
                preco=preco,
                minimo=minimo,
                maximo=maximo,
                repetir=repetir,
                metodo_preco=1,
            ))

        if validos:
            grupos_escritos.add(gid)
            res.grupos.extend(validos)


def _byfood_enriquecer_detalhes(url, html, res):
    """
    Usa os IDs/onclick da própria página e consulta diretamente
    /produtos/visualizar/{produto_id}.
    """
    purl = urlparse(url)
    base = f"{purl.scheme or 'https'}://{purl.netloc}"
    soup = BeautifulSoup(html or "", "html.parser")

    # nome -> produto já extraído
    produtos = res.itens + res.pizzas
    por_nome = {_normalizar_nome_produto(p.nome): p for p in produtos if p.nome}
    grupos_escritos = set()

    session = requests.Session()
    session.headers.update(HEADERS)
    try:
        session.get(url, timeout=30)
    except Exception:
        pass

    candidatos = []
    vistos = set()

    for el in soup.select("[onclick*='/produtos/visualizar/'], [data-produto-id]"):
        onclick = el.get("onclick") or ""
        pid = el.get("data-produto-id")
        if not pid:
            m = re.search(r"/produtos/visualizar/(\d+)", onclick)
            if m:
                pid = m.group(1)
        if not pid or str(pid) in vistos:
            continue
        vistos.add(str(pid))

        nome = ""
        # O onclick da byFood traz item_name para analytics.
        mname = re.search(r"item_name:'([^']+)'", onclick)
        if mname:
            nome = mname.group(1)
        if not nome:
            txt = re.sub(r"\s+", " ", el.get_text(" ", strip=True)).strip()
            # limpa prefixos promocionais/pontos e corta no preço
            txt = re.split(r"R\$", txt, maxsplit=1)[0]
            txt = re.sub(r"^\s*\d+%\s*OFF\s*", "", txt, flags=re.I)
            txt = re.sub(r"^\s*\d+\s*pontos?\s*", "", txt, flags=re.I)
            nome = txt.strip()

        candidatos.append((str(pid), nome))

    # Tenta associar por nome; se o código já for o ID, associa por código.
    for pid, nome in candidatos:
        prod = next((p for p in produtos if str(p.codigo) == pid), None)
        if prod is None:
            n = _normalizar_nome_produto(nome)
            prod = por_nome.get(n)
        if prod is None and nome:
            n = _normalizar_nome_produto(nome)
            # aproximação simples para títulos com pequenas diferenças de promoção
            for k, p in por_nome.items():
                if n and (n in k or k in n):
                    prod = p
                    break
        if prod is None:
            continue

        prod.codigo = pid

        try:
            r = session.get(
                f"{base}/produtos/visualizar/{pid}",
                headers={
                    "Referer": url,
                    "X-Requested-With": "XMLHttpRequest",
                    "Accept": "text/html, */*; q=0.01",
                },
                timeout=30,
            )
            r.raise_for_status()
            _byfood_parse_detail_html(r.text, res, prod, grupos_escritos)
        except Exception as e:
            res.avisos.append(f"byFood: detalhe do produto {pid} não pôde ser lido: {e}")

    return res



def buscar_rapidfood(url):
    """
    RapidFood FINAL CORRIGIDA.

    Fonte principal:
      openProductModal({...}) -> produtos/categorias
      /store/get_product_options.php?product_id=ID -> adicionais
    """
    # Renderizado é necessário para garantir todos os produtos.
    html = render_playwright(url)
    dados = _rapidfood_produtos_do_dom(html)

    # Fallback para HTML estático se necessário.
    if not dados:
        html = get(url).text
        dados = _rapidfood_produtos_do_dom(html)

    if not dados:
        # Mantém fallback universal em caso de mudança futura da plataforma.
        res = interpretar_html(html, origem="RapidFood FINAL / fallback DOM")
        res = limpar_resultado_generico(res, "RapidFood")
        res.origem = "RapidFood FINAL / fallback DOM"
        return res

    res = Resultado(origem="RapidFood FINAL / openProductModal + API opções")
    grupos_escritos = set()
    vistos = set()

    session = requests.Session()
    session.headers.update(HEADERS)
    try:
        session.get(url, timeout=30)
    except Exception:
        pass

    for obj in dados:
        pid = str(obj.get("id") or "")
        if not pid or pid in vistos:
            continue
        vistos.add(pid)

        nome = texto_seguro(obj.get("nome") or "")
        desc = texto_seguro(obj.get("descricao") or "")
        categoria = texto_seguro(obj.get("categoria_nome") or "")
        preco = parse_preco(
            obj.get("preco_display")
            if obj.get("preco_display") not in (None, "")
            else obj.get("preco")
        )

        prod = Produto(
            codigo=pid,
            nome=nome,
            descricao=desc,
            categoria=categoria,
            imagem=imagem_compativel(obj.get("imagem_url") or ""),
            preco=preco,
            grupos=[],
            pizza=parece_pizza(nome, categoria, desc),
            combo=parece_combo(nome, categoria, desc),
        )

        try:
            # FINAL: usa a origem exata da loja e replica cabeçalhos de uma chamada AJAX.
            # Isso evita perder sessão/referer e elimina a dependência de domínio fixo.
            purl = urlparse(url)
            base = f"{purl.scheme or 'https'}://{purl.netloc}"
            endpoint = f"{base}/store/get_product_options.php"

            rr = session.get(
                endpoint,
                params={"product_id": pid},
                headers={
                    "Accept": "application/json, text/javascript, */*; q=0.01",
                    "Referer": url,
                    "X-Requested-With": "XMLHttpRequest",
                },
                timeout=30,
            )
            rr.raise_for_status()

            # Alguns servidores podem responder JSON com Content-Type impreciso.
            try:
                data = rr.json()
            except Exception:
                data = json.loads(rr.text)

            antes = len(res.grupos)
            _rapidfood_parse_options_payload(data, res, prod, grupos_escritos)

            # Diagnóstico útil sem interromper a geração.
            if isinstance(data, dict) and data.get("success") and len(res.grupos) == antes:
                opgroups = data.get("options") or []
                if any((g.get("opcoes") or []) for g in opgroups if isinstance(g, dict)):
                    res.avisos.append(
                        f"RapidFood FINAL: API retornou opções para {pid}, mas nenhuma opção válida foi convertida."
                    )
        except Exception as e:
            res.avisos.append(f"RapidFood: adicionais do produto {pid} não puderam ser lidos: {e}")

        (res.pizzas if prod.pizza and not prod.combo else res.itens).append(prod)

    _dedupe_result(res)
    return res

def buscar_byfood(url):
    """
    byFood FINAL — parser específico baseado na estrutura real observada.

    A byFood entrega o cardápio no HTML/DOM. O parser:
    - encontra imagens em /produtos/ e usa o menor ancestral com preço;
    - extrai nome de headings, alt/title e textos próximos;
    - extrai preço do próprio card;
    - tenta inferir categoria pelo bloco/seção imediatamente anterior;
    - deduplica fortemente para evitar o mesmo produto por múltiplos wrappers.
    """
    html = render_playwright(url)
    soup = BeautifulSoup(html, "html.parser")
    res = Resultado(origem="byFood FINAL / DOM específico")

    def _txt(el):
        return re.sub(r"\s+", " ", el.get_text(" ", strip=True)) if el else ""

    def _preco(txt):
        vals = re.findall(r"R\$\s*([\d\.\,]+)", txt or "", re.I)
        if not vals:
            return 0.0
        # Usa o último preço do card; normalmente evita preço riscado/promocional anterior.
        return parse_preco(vals[-1])

    def _produto_img(img):
        src = (
            img.get("data-src") or img.get("src") or img.get("data-original") or
            img.get("data-lazy") or ""
        )
        s = src.lower()
        return ("produtos/" in s or "/produtos/" in s) and "categorias_produtos" not in s

    # Mapa aproximado de headings/categorias por posição no documento.
    categorias_por_elemento = []
    for h in soup.find_all(["h1","h2","h3","h4","h5","h6"]):
        t = _txt(h)
        if t and "R$" not in t and len(t) < 100:
            categorias_por_elemento.append((h, t))

    def _categoria_para(card):
        # Primeiro tenta atributos/classes locais.
        cur = card
        for _ in range(5):
            if not cur:
                break
            for attr in ("data-categoria","data-category","data-category-name","data-secao-nome"):
                v = cur.get(attr)
                if v:
                    return texto_seguro(v)
            cur = cur.parent

        # Procura heading anterior mais próximo no fluxo HTML.
        prev = card
        for _ in range(40):
            prev = prev.find_previous()
            if prev is None:
                break
            if getattr(prev, "name", None) in ("h1","h2","h3","h4","h5","h6"):
                t = _txt(prev)
                if t and "R$" not in t and len(t) < 100:
                    if t.lower() not in {"cardápio","cardapio","categorias","categoria"}:
                        return texto_seguro(t)
        return ""

    candidatos = []
    for img in soup.find_all("img"):
        if not _produto_img(img):
            continue

        src = (
            img.get("data-src") or img.get("src") or img.get("data-original") or
            img.get("data-lazy") or ""
        )

        # Sobe até achar um wrapper pequeno que contenha preço.
        card = img
        escolhido = None
        for _ in range(8):
            card = card.parent
            if card is None:
                break
            txt = _txt(card)
            if "R$" in txt and 4 <= len(txt) <= 1200:
                escolhido = card
                # prefere wrappers com indícios de produto
                cls = " ".join(card.get("class") or []).lower()
                if any(k in cls for k in ("produto","product","item","card")):
                    break
        if escolhido is None:
            continue

        candidatos.append((escolhido, src, img))

    # Deduplica wrappers equivalentes.
    unicos = []
    seen_sig = set()
    for card, src, img in candidatos:
        txt = _txt(card)
        sig = (src.split("?")[0], re.sub(r"\s+"," ",txt)[:500])
        if sig in seen_sig:
            continue
        seen_sig.add(sig)
        unicos.append((card, src, img))

    vistos_prod = set()

    for card, src, img in unicos:
        raw = _txt(card)
        preco = _preco(raw)
        if preco <= 0 and "R$" not in raw:
            continue

        # Nome: tenta dados/onclick primeiro.
        nome = ""
        for el in [card] + card.find_all(True, limit=40):
            for attr in ("data-name","data-nome","data-product-name","data-produto-nome","title","aria-label"):
                v = el.get(attr)
                if v and len(str(v).strip()) <= 140:
                    cand = texto_seguro(str(v).strip())
                    if cand and "R$" not in cand:
                        nome = cand
                        break
            if nome:
                break

        # Headings/strongs dentro do card.
        if not nome:
            for sel in ("h3","h4","h5","h6","strong","b",".nome",".name",".titulo",".title"):
                el = card.select_one(sel)
                if el:
                    cand = texto_seguro(_txt(el))
                    if cand and "R$" not in cand and len(cand) <= 140:
                        nome = cand
                        break

        # Alt/title da imagem.
        if not nome:
            nome = texto_seguro((img.get("alt") or img.get("title") or "").strip())

        # Fallback por linhas do texto do card.
        if not nome:
            partes = [p.strip() for p in re.split(r"(?:\n|\r|R\$)", raw) if p.strip()]
            for p in partes:
                if len(p) <= 140 and not re.fullmatch(r"[\d\.,\s]+", p):
                    nome = texto_seguro(p)
                    break

        if not nome:
            # Deriva nome do filename da imagem como último recurso.
            fn = src.split("/")[-1].split("?")[0]
            fn = re.sub(r"[-_][0-9a-f]{8,}.*$", "", fn, flags=re.I)
            fn = re.sub(r"\.(png|jpe?g|webp|gif)$", "", fn, flags=re.I)
            fn = fn.replace("_", " ").replace("-", " ").strip()
            nome = texto_seguro(re.sub(r"\s+"," ", fn))

        if not nome:
            continue

        # Remove ruídos de UI.
        if _norm_ui(nome) in _UI_EXACT or any(_norm_ui(nome).startswith(x) for x in _UI_PREFIX):
            continue

        categoria = _categoria_para(card)

        # Descrição curta: tenta elementos de descrição.
        desc = ""
        for sel in (".descricao",".description",".desc",".produto-descricao",".product-description","p"):
            el = card.select_one(sel)
            if el:
                cand = texto_seguro(_txt(el))
                if cand and cand != nome and "R$" not in cand and len(cand) <= 500:
                    desc = cand
                    break

        codigo = ""
        for el in [card] + card.find_all(True, limit=30):
            for attr in ("data-produto-id","data-product-id","data-id","id"):
                v = el.get(attr)
                if v and len(str(v)) <= 80:
                    codigo = str(v)
                    break
            if codigo:
                break
        if not codigo:
            codigo = "byf-" + re.sub(r"[^a-z0-9]+","-", nome.lower()).strip("-")[:50]

        key = (nome.lower(), round(float(preco or 0), 2), categoria.lower())
        if key in vistos_prod:
            continue
        vistos_prod.add(key)

        p = Produto(
            codigo=codigo,
            nome=nome,
            descricao=desc,
            categoria=categoria,
            imagem=imagem_compativel(src),
            preco=preco,
            grupos=[],
            pizza=parece_pizza(nome, categoria, desc),
            combo=parece_combo(nome, categoria, desc),
        )

        (res.pizzas if p.pizza and not p.combo else res.itens).append(p)

    # Se ainda estiver muito fraco, usa parser universal e mantém o mais rico.
    if len(res.itens) + len(res.pizzas) < 5:
        gen = interpretar_html(html, origem="byFood FINAL / fallback universal")
        gen = limpar_resultado_generico(gen, "byFood")
        if _resultado_melhor_que(gen, res):
            res = gen

    res.origem = "byFood FINAL / DOM específico + detalhes"
    _dedupe_result(res)

    # FINAL CORRIGIDA: consulta o detalhe de cada produto para montar adicionais.
    try:
        _byfood_enriquecer_detalhes(url, html, res)
    except Exception as e:
        res.avisos.append(f"byFood: enriquecimento de adicionais falhou: {e}")

    _dedupe_result(res)
    return res

def _parse_instadelivery_payload(data):
    """
    InstaDelivery DEFINITIVO.

    A própria página pública requisita:
      https://app.instadelivery.com.br/api/stores/by-slug/{slug}

    Esse payload contém `groups -> itens`, e o preço exibido do produto
    está em `price1`.

    Importante:
    - NÃO inferir preço a partir de complementos;
    - NÃO usar price2 como preço-base;
    - NÃO usar strike_price como preço atual;
    - manter complementos normalmente.
    """
    if not isinstance(data, dict):
        raise ValueError("InstaDelivery: payload inválido.")

    res = Resultado(origem="InstaDelivery DEFINITIVO / API by-slug")
    written = set()

    for grupo in data.get("groups", []) or []:
        if not isinstance(grupo, dict):
            continue
        if grupo.get("is_invisible"):
            continue

        cat = texto_seguro(grupo.get("name") or "")

        for item in grupo.get("itens", []) or []:
            if not isinstance(item, dict):
                continue
            if item.get("is_invisible"):
                continue
            if item.get("deleted_at"):
                continue

            gids = []

            for cg in item.get("complementos", []) or []:
                if not isinstance(cg, dict):
                    continue

                opts = []
                for o in cg.get("complements", []) or []:
                    if not isinstance(o, dict):
                        continue
                    if o.get("is_invisible") or o.get("deleted_at"):
                        continue

                    opts.append(GrupoOpcao(
                        grupo_id=str(cg.get("id")),
                        tipo=tipo_grupo(cg.get("name")),
                        grupo_nome=texto_seguro(cg.get("name")),
                        nome=texto_seguro(o.get("name")),
                        imagem=imagem_compativel(o.get("image")),
                        preco=parse_preco(o.get("price")),
                        minimo=int(cg.get("min") or 0),
                        maximo=int(cg.get("max") or 1),
                    ))

                if opts:
                    gid = str(cg.get("id"))
                    gids.append(gid)

                    if gid not in written:
                        written.add(gid)
                        res.grupos.extend(opts)

            nome = texto_seguro(item.get("name"))
            desc = texto_seguro(item.get("description"))

            # REGRA DEFINITIVA:
            # price1 é o preço-base atual exibido no cardápio.
            # Exemplos reais da loja testada:
            # Coca-Cola 350ml = 9
            # Coca-Cola 2 Litros = 17
            # Guaraná Antártica 2 Litros = 15
            # Kuat guaraná 2 litros = 10 (strike_price 12)
            preco_base = parse_preco(item.get("price1"))

            prod = Produto(
                codigo=str(item.get("id") or len(res.itens) + len(res.pizzas) + 1),
                nome=nome,
                descricao=desc,
                categoria=cat,
                imagem=imagem_compativel(item.get("image")),
                preco=preco_base,
                grupos=gids,
                pizza=parece_pizza(nome, cat, desc),
                combo=parece_combo(nome, cat, desc),
            )

            (res.pizzas if prod.pizza and not prod.combo else res.itens).append(prod)

    _dedupe_result(res)
    return res


def buscar_instadelivery(url):
    m = re.search(r"instadelivery\.com\.br/([^/?#]+)", url)
    if not m:
        raise ValueError("URL InstaDelivery inválida.")

    slug = m.group(1)
    base = f"https://app.instadelivery.com.br/api/stores/by-slug/{slug}"

    # Usa primeiro a MESMA API que a página pública requisitou no diagnóstico.
    try:
        data = get(base, headers={"Accept": "application/json"}).json()
        res = _parse_instadelivery_payload(data)
        if res.itens or res.pizzas:
            return res
    except Exception as e:
        erro_principal = e
    else:
        erro_principal = ValueError("API principal retornou cardápio vazio.")

    # Fallback apenas se a API principal realmente falhar.
    # Não é usado para substituir preços quando a API principal responde.
    try:
        data = get(base + "/table", headers={"Accept": "application/json"}).json()
        res = _parse_instadelivery_payload(data)
        res.avisos.append(
            "InstaDelivery: foi necessário usar o endpoint /table como fallback."
        )
        return res
    except Exception as e:
        raise ValueError(
            f"InstaDelivery: API principal falhou ({erro_principal}); "
            f"fallback /table também falhou ({e})."
        )


def buscar_brendi(url):
    m = re.search(r"(?:pedido\.)?brendi\.com\.br/([^/?#]+)", url)
    if not m:
        raise ValueError("URL Brendi inválida.")
    slug = m.group(1)
    data = get(f"https://pedido.brendi.com.br/api/{slug}/menu", headers={"Accept":"application/json"}).json()
    data = data.get("data") or data
    cats = data.get("categories") or []
    by_cat = data.get("productsByCategory") or {}
    res = Resultado(origem="Brendi")
    gid_map = {}
    seq = 9000000
    for cat in cats:
        if cat.get("active") is False:
            continue
        cat_name = texto_seguro(cat.get("name"))
        for p in by_cat.get(str(cat.get("id")), by_cat.get(cat.get("id"), [])) or []:
            if p.get("active") is False:
                continue
            gids = []
            grupos_brendi = (
                p.get("customs") or p.get("modifierGroups") or p.get("modifier_groups") or
                p.get("optionGroups") or p.get("option_groups") or p.get("add_ons") or []
            )
            for g_idx, g in enumerate(grupos_brendi):
                if g.get("active") is False:
                    continue

                # Brendi nem sempre envia ID para o grupo. Antes, todos os grupos
                # sem ID viravam a chave literal "None" e acabavam fundidos no
                # mesmo grupo (9000000), gerando opções duplicadas.
                raw_group_id = g.get("id")
                if raw_group_id not in (None, ""):
                    raw_id = f"id:{raw_group_id}"
                else:
                    raw_id = (
                        f"produto:{p.get('id') or 'sem-id'}:"
                        f"grupo:{g_idx}:"
                        f"{texto_seguro(g.get('title')).strip().lower()}"
                    )

                if raw_id not in gid_map:
                    gid_map[raw_id] = str(seq); seq += 1
                gid = gid_map[raw_id]
                valid = []
                opcoes_vistas_brendi = set()
                for o in g.get("choices", []) or []:
                    if o.get("active") is False:
                        continue

                    nome_opcao = texto_seguro(o.get("title"))
                    preco_opcao = parse_preco(o.get("extraPrice"))/100.0
                    chave_opcao = (nome_opcao.strip().lower(), round(float(preco_opcao or 0), 6))
                    if chave_opcao in opcoes_vistas_brendi:
                        continue
                    opcoes_vistas_brendi.add(chave_opcao)

                    valid.append(GrupoOpcao(
                        grupo_id=gid, tipo=tipo_grupo(g.get("title")),
                        grupo_nome=texto_seguro(g.get("title")),
                        nome=nome_opcao,
                        imagem=imagem_compativel(o.get("picture")),
                        preco=preco_opcao,
                        minimo=1 if g.get("required") else 0,
                        maximo=(len(g.get("choices") or []) or 1) if g.get("type")=="multiple" else 1
                    ))
                if valid:
                    if gid not in gids:
                        gids.append(gid)
                    res.grupos.extend(valid)
            if not gids:
                gids = _materializar_grupos_genericos(
                    res, p, prefixo=f"brendi-{p.get('id') or len(res.itens)+1}"
                )
            nome = texto_seguro(p.get("name") or p.get("title"))
            desc = texto_seguro(p.get("description"))
            prod = Produto(
                codigo=str(p.get("id") or len(res.itens)+len(res.pizzas)+1),
                nome=nome, descricao=desc, categoria=cat_name,
                imagem=imagem_compativel(p.get("picture") or p.get("image")),
                preco=parse_preco(p.get("currentPrice") if p.get("currentPrice") is not None else p.get("price"))/100.0,
                grupos=gids, pizza=parece_pizza(nome, cat_name, desc), combo=parece_combo(nome, cat_name, desc)
            )
            (res.pizzas if prod.pizza and not prod.combo else res.itens).append(prod)
    return res

def buscar_olaclick(url):
    """
    Ola Click FINAL CORRIGIDA.
    O fluxo principal usa __NUXT_DATA__ capturado pelo diagnóstico.
    Este método é somente fallback.
    """
    html = render_playwright(url)
    soup = BeautifulSoup(html, "html.parser")
    sc = soup.find("script", id="__NUXT_DATA__")
    if sc:
        raw = (sc.string or sc.get_text() or "").strip()
        if raw:
            try:
                return _parse_olaclick_nuxt_data(json.loads(raw))
            except Exception:
                pass

    gen = interpretar_html(html, origem="Ola Click FINAL CORRIGIDA / fallback DOM")
    gen = limpar_resultado_generico(gen, "Ola Click")
    return gen


def buscar_menui(url):
    """
    Menu Integrado FINAL CORRIGIDA.
    Fonte confirmada: /internal/categories?channel=platform
    """
    p = urlparse(url)
    base = f"{p.scheme or 'https'}://{p.netloc}"
    try:
        data = get(
            base + "/internal/categories?channel=platform",
            headers={"Accept": "application/json"}
        ).json()
        res = _parse_menuintegrado_categories(data)
        if res.itens or res.pizzas:
            return res
    except Exception:
        pass

    # Somente fallback de segurança.
    gen = interpretar_html(render_playwright(url), origem="Menui / Menu Integrado FINAL CORRIGIDA / fallback DOM")
    gen = limpar_resultado_generico(gen, "Menui")
    return gen


def buscar_cardapioweb(url, diagnostico=False):
    """
    Cardápio Web FINAL.

    Fonte principal:
      /api/menu/company/categories?only_available_for=delivery&origin=catalogo

    O diagnóstico V5 mostrou que esse endpoint retorna a estrutura grande do
    cardápio. A V6 deixa de varrer todos os JSONs como fonte principal e passa
    a interpretar diretamente:
        categoria -> items -> produto -> grupos -> opções

    A leitura genérica V4/V5 continua como fallback.
    """
    from playwright.sync_api import sync_playwright

    respostas = []
    eventos = []
    categories_data = None
    profile_data = None
    html_renderizado = ""

    def resumir_json(data):
        info = {
            "tipo_raiz": type(data).__name__,
            "tem_produtos": False,
            "tem_categorias": False,
            "tem_grupos": False,
            "tem_precos": False,
            "chaves_amostra": [],
        }
        product_re = re.compile(r"(product|produto|item_name|itemname|menu_item|menuitem|items)", re.I)
        category_re = re.compile(r"(categor|cate_|section|secao)", re.I)
        group_re = re.compile(
            r"(additional|addon|complement|modifier|option|custom|extra|ingredient|"
            r"component|choice|variation|sku_group|tag_group|food_tag|group)",
            re.I,
        )
        price_re = re.compile(r"(price|preco|valor|amount|selling_price|sale_price|final_price)", re.I)

        seen = set()
        def walk(obj, depth=0):
            if depth > 10:
                return
            oid = id(obj)
            if oid in seen:
                return
            seen.add(oid)

            if isinstance(obj, dict):
                if depth <= 2 and len(info["chaves_amostra"]) < 50:
                    for k in obj.keys():
                        ks = str(k)
                        if ks not in info["chaves_amostra"]:
                            info["chaves_amostra"].append(ks)
                for k, v in obj.items():
                    ks = str(k)
                    if product_re.search(ks):
                        info["tem_produtos"] = True
                    if category_re.search(ks):
                        info["tem_categorias"] = True
                    if group_re.search(ks):
                        info["tem_grupos"] = True
                    if price_re.search(ks):
                        info["tem_precos"] = True
                    if isinstance(v, (dict, list)):
                        walk(v, depth + 1)
            elif isinstance(obj, list):
                for x in obj[:1000]:
                    if isinstance(x, (dict, list)):
                        walk(x, depth + 1)

        walk(data)
        return info

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            locale="pt-BR",
            viewport={"width": 1440, "height": 1200},
            user_agent=HEADERS["User-Agent"],
        )
        page = context.new_page()

        def on_response(resp):
            nonlocal categories_data, profile_data
            evento = {
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "url": resp.url,
                "status": resp.status,
                "ok": 200 <= resp.status < 300,
                "resource_type": getattr(resp.request, "resource_type", ""),
                "method": getattr(resp.request, "method", ""),
                "content_type": "",
                "json": False,
                "json_summary": None,
                "body_size": None,
            }

            try:
                evento["content_type"] = resp.headers.get("content-type") or ""
            except Exception:
                pass

            try:
                body = resp.body()
                evento["body_size"] = len(body)
            except Exception:
                pass

            data = None
            try:
                ct = evento["content_type"].lower()
                u = resp.url.lower()
                if "json" in ct or "integracao.cardapioweb.com" in u:
                    data = resp.json()
            except Exception:
                data = None

            if data is not None:
                evento["json"] = True
                evento["json_summary"] = resumir_json(data)
                u = resp.url.lower()

                if (
                    "/api/menu/company/categories" in u
                    and "only_available_for=delivery" in u
                    and 200 <= resp.status < 300
                ):
                    categories_data = data

                if "/api/menu/company/profile" in u and 200 <= resp.status < 300:
                    profile_data = data

                if "integracao.cardapioweb.com" in u and 200 <= resp.status < 300:
                    respostas.append({
                        "url": resp.url,
                        "data": data,
                        "status": resp.status,
                        "resource_type": evento["resource_type"],
                        "method": evento["method"],
                        "content_type": evento["content_type"],
                        "json_summary": evento["json_summary"],
                    })

            eventos.append(evento)

        page.on("response", on_response)
        page.goto(url, wait_until="domcontentloaded", timeout=60000)

        # O endpoint de categorias normalmente chega logo no carregamento.
        # Mantemos uma espera curta + rolagem para garantir itens lazy.
        page.wait_for_timeout(2800)
        for _ in range(6):
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(350)
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(500)

        html_renderizado = page.content()
        browser.close()

    # -------------------------------
    # FONTE PRINCIPAL V6
    # -------------------------------
    if isinstance(categories_data, list):
        res = _cardapioweb_categories_v6(categories_data)
        fonte = "endpoint categories"
    else:
        # Fallback para o parser genérico já consolidado.
        res = _cardapioweb_de_respostas(respostas)
        fonte = "fallback JSON genérico"

    if not res.itens and not res.pizzas:
        res = _cardapioweb_do_dom(html_renderizado)
        fonte = "fallback DOM"

    res.origem = (
        f"Cardápio Web FINAL — {fonte} "
        f"({len(respostas)} JSON, {len(eventos)} respostas observadas)"
    )

    # Diagnóstico: agora inclui o RAW do endpoint principal.
    audit_resumo = getattr(res, "_cardapioweb_audit", None)

    diagnostico_obj = {
        "versao": "FINAL",
        "url_loja": url,
        "gerado_em": datetime.now().isoformat(timespec="seconds"),
        "fonte_principal": fonte,
        "total_respostas_observadas": len(eventos),
        "total_json_util": len(respostas),
        "total_produtos": len(res.itens) + len(res.pizzas),
        "total_regulares": len(res.itens),
        "total_pizzas": len(res.pizzas),
        "total_opcoes_adicionais": len(res.grupos),
        "total_grupos_distintos": len({str(g.grupo_id) for g in res.grupos}),
        "total_vinculos_produto_grupo": sum(
            len(p.grupos or []) for p in (res.itens + res.pizzas)
        ),
        "auditoria_cardapioweb": audit_resumo,
        "categories_raw": categories_data,
        "profile_raw": profile_data,
        "eventos": eventos,
    }

    try:
        setattr(res, "_diagnostico_rede", diagnostico_obj)
    except Exception:
        pass

    return res


def _cardapioweb_categories_v6(categories):
    """
    Cardápio Web FINAL — parser final direto + auditoria estrita.

    Estrutura confirmada no JSON bruto:
        categorias[] -> items[] -> add_ons[] -> subitems[]

    A V8:
    - usa IDs reais do Cardápio Web;
    - deduplica grupo pelo ID real;
    - valida se o mesmo ID de grupo mantém a mesma configuração;
    - preserva todos os vínculos produto -> grupo;
    - calcula contagens esperadas diretamente da API;
    - salva uma auditoria no Resultado para o validator bloquear o XLSX
      caso qualquer contagem/vínculo fique inconsistente.
    """
    res = Resultado(origem="Cardápio Web FINAL")

    produtos_vistos = set()
    assinaturas_sem_id = set()
    grupos_materializados = {}   # gid -> assinatura
    grupos_opcoes_ids = {}       # gid -> set(subitem ids/signatures)
    conflitos_grupo = []

    audit = {
        "categorias_active": 0,
        "produtos_active_api": 0,
        "produtos_ids_unicos_api": 0,
        "grupos_ocorrencias_api": 0,
        "grupos_ids_unicos_api": 0,
        "subitens_ocorrencias_api": 0,
        "subitens_ids_unicos_api": 0,
        "opcoes_unicas_por_grupo_api": 0,
        "vinculos_produto_grupo_api": {},
        "conflitos_grupo": [],
    }

    api_product_ids = set()
    api_group_ids = set()
    api_subitem_ids = set()
    api_unique_option_pairs = set()

    def norm(v):
        return re.sub(r"\s+", " ", str(v or "").strip()).lower()

    def ativo(obj):
        if not isinstance(obj, dict):
            return False
        status = str(obj.get("status") or "ACTIVE").strip().upper()
        if status in ("INACTIVE", "DISABLED", "HIDDEN", "DELETED"):
            return False
        for k in ("active", "enabled", "available", "visible", "is_active", "isActive"):
            if k in obj and obj.get(k) is False:
                return False
        return True

    def nome(obj):
        if not isinstance(obj, dict):
            return ""
        for k in ("name", "nome", "title", "titulo", "label"):
            v = obj.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
        return ""

    def descricao(obj):
        if not isinstance(obj, dict):
            return ""
        for k in ("description", "descricao", "subtitle", "subtitulo", "details", "detalhes"):
            v = obj.get(k)
            if isinstance(v, str) and v.strip():
                return texto_seguro(v)
        return ""

    def imagem(obj):
        if not isinstance(obj, dict):
            return ""
        for k in (
            "image_url", "imageUrl", "thumbnail_url", "thumbnailUrl",
            "photo", "foto", "picture", "cover", "url_image", "urlImage"
        ):
            v = obj.get(k)
            if isinstance(v, str) and v.strip():
                return imagem_compativel(v.strip())

        image_obj = obj.get("image") or obj.get("imagem")
        if isinstance(image_obj, dict):
            for k in ("image_url", "imageUrl", "thumbnail_url", "thumbnailUrl", "url"):
                v = image_obj.get(k)
                if isinstance(v, str) and v.strip():
                    return imagem_compativel(v.strip())
        elif isinstance(image_obj, str) and image_obj.strip():
            return imagem_compativel(image_obj.strip())
        return ""

    def preco_produto(obj):
        # Importante: usa preço base do catálogo.
        for k in ("price", "preco", "selling_price", "sellingPrice", "value", "valor"):
            if k in obj and obj.get(k) is not None:
                return parse_preco(obj.get(k))
        return 0.0

    def preco_subitem(obj):
        for k in (
            "price", "additional_price", "additionalPrice",
            "extra_price", "extraPrice", "value", "valor"
        ):
            if k in obj and obj.get(k) is not None:
                return parse_preco(obj.get(k))
        return 0.0

    def int_val(obj, keys, default):
        for k in keys:
            if obj.get(k) not in (None, ""):
                try:
                    return int(float(obj.get(k)))
                except Exception:
                    pass
        return default

    def subitem_key(s):
        sid = s.get("id")
        if sid not in (None, ""):
            return str(sid)
        return f"sig:{norm(nome(s))}|{preco_subitem(s):.6f}|{norm(imagem(s))}"

    def assinatura_grupo(g):
        subs = []
        for s in (g.get("subitems") or []):
            if not isinstance(s, dict) or not ativo(s) or not nome(s):
                continue
            subs.append((
                subitem_key(s),
                norm(nome(s)),
                round(preco_subitem(s), 6),
                norm(imagem(s)),
            ))
        # position NÃO faz parte da assinatura porque o mesmo grupo
        # pode estar em posições diferentes em produtos diferentes.
        return (
            norm(nome(g)),
            int_val(g, ("minimum_quantity", "minimum", "min"), 0),
            int_val(g, ("maximum_quantity", "maximum", "max"), 1),
            str(g.get("choice_type") or "").upper(),
            str(g.get("price_calculation_type") or "").upper(),
            tuple(subs),
        )

    # -------------------------------------------------
    # PRÉ-AUDITORIA: conta exatamente o que existe na API
    # -------------------------------------------------
    for categoria_obj in categories or []:
        if not isinstance(categoria_obj, dict) or not ativo(categoria_obj):
            continue
        audit["categorias_active"] += 1

        for item in (categoria_obj.get("items") or []):
            if not isinstance(item, dict) or not ativo(item):
                continue

            audit["produtos_active_api"] += 1
            pid = item.get("id")
            pkey = str(pid) if pid not in (None, "") else f"sem-id:{audit['produtos_active_api']}"
            if pid not in (None, ""):
                api_product_ids.add(str(pid))

            vinculos = []
            for g in (item.get("add_ons") or []):
                if not isinstance(g, dict) or not ativo(g):
                    continue
                gid = g.get("id")
                if gid in (None, ""):
                    continue
                gid = str(gid)
                audit["grupos_ocorrencias_api"] += 1
                api_group_ids.add(gid)
                if gid not in vinculos:
                    vinculos.append(gid)

                for s in (g.get("subitems") or []):
                    if not isinstance(s, dict) or not ativo(s) or not nome(s):
                        continue
                    audit["subitens_ocorrencias_api"] += 1
                    skey = subitem_key(s)
                    api_subitem_ids.add(skey)
                    api_unique_option_pairs.add((gid, skey))

            audit["vinculos_produto_grupo_api"][pkey] = vinculos

    audit["produtos_ids_unicos_api"] = len(api_product_ids)
    audit["grupos_ids_unicos_api"] = len(api_group_ids)
    audit["subitens_ids_unicos_api"] = len(api_subitem_ids)
    audit["opcoes_unicas_por_grupo_api"] = len(api_unique_option_pairs)

    # -------------------------------------------------
    # MATERIALIZAÇÃO
    # -------------------------------------------------
    def materializar_grupo(g):
        if not isinstance(g, dict) or not ativo(g):
            return None

        raw_gid = g.get("id")
        if raw_gid in (None, ""):
            return None
        gid = str(raw_gid)

        subs = [
            s for s in (g.get("subitems") or [])
            if isinstance(s, dict) and ativo(s) and nome(s)
        ]
        if not subs:
            return None

        sig = assinatura_grupo(g)

        if gid in grupos_materializados:
            if grupos_materializados[gid] != sig:
                conflitos_grupo.append(
                    f'Grupo ID {gid} ("{nome(g)}") apareceu com configurações/opções diferentes.'
                )
            return gid

        grupos_materializados[gid] = sig
        grupos_opcoes_ids[gid] = set()

        nome_g = texto_seguro(nome(g) or "Adicionais")
        minimo = int_val(g, ("minimum_quantity", "minimum", "min"), 0)
        maximo = int_val(g, ("maximum_quantity", "maximum", "max"), 1)
        if maximo <= 0:
            maximo = max(1, len(subs))

        for s in subs:
            skey = subitem_key(s)
            if skey in grupos_opcoes_ids[gid]:
                continue
            grupos_opcoes_ids[gid].add(skey)

            res.grupos.append(
                GrupoOpcao(
                    grupo_id=gid,
                    tipo=tipo_grupo(nome_g),
                    grupo_nome=nome_g,
                    nome=texto_seguro(nome(s)),
                    imagem=imagem(s),
                    preco=preco_subitem(s),
                    minimo=minimo,
                    maximo=maximo,
                    repetir=0,
                    metodo_preco=1,
                )
            )
        return gid

    for categoria_obj in categories or []:
        if not isinstance(categoria_obj, dict) or not ativo(categoria_obj):
            continue

        categoria = texto_seguro(nome(categoria_obj))
        items = categoria_obj.get("items") or []
        if not isinstance(items, list):
            continue

        for item in items:
            if not isinstance(item, dict) or not ativo(item):
                continue

            nome_item = texto_seguro(nome(item))
            if not nome_item:
                continue

            raw_id = item.get("id")
            codigo = str(raw_id) if raw_id not in (None, "") else ""

            if codigo:
                if codigo in produtos_vistos:
                    # ID repetido em mais de uma categoria: mantém apenas uma entidade,
                    # mas o validator vai detectar diferença entre API ACTIVE e saída.
                    continue
                produtos_vistos.add(codigo)

            desc = descricao(item)
            img = imagem(item)
            preco = preco_produto(item)

            if not codigo:
                sig_item = (
                    norm(nome_item), round(preco, 6), norm(categoria), norm(desc), norm(img)
                )
                if sig_item in assinaturas_sem_id:
                    continue
                assinaturas_sem_id.add(sig_item)
                codigo = f"sem-id-{len(assinaturas_sem_id)}"

            gids = []
            for g in (item.get("add_ons") or []):
                gid = materializar_grupo(g)
                if gid and gid not in gids:
                    gids.append(gid)

            combo = parece_combo(nome_item, categoria, desc)
            pizza = parece_pizza(nome_item, categoria, desc)

            prod = Produto(
                codigo=codigo,
                nome=nome_item,
                descricao=desc,
                categoria=categoria,
                imagem=img,
                preco=preco,
                grupos=gids,
                pizza=bool(pizza and not combo),
                combo=bool(combo),
            )

            if prod.pizza:
                res.pizzas.append(prod)
            else:
                res.itens.append(prod)

    # Grupos órfãos jamais entram no XLSX.
    usados = {
        str(gid)
        for p in (res.itens + res.pizzas)
        for gid in (p.grupos or [])
    }
    res.grupos = [g for g in res.grupos if str(g.grupo_id) in usados]

    audit["conflitos_grupo"] = conflitos_grupo
    audit["produtos_saida"] = len(res.itens) + len(res.pizzas)
    audit["grupos_ids_saida"] = len({str(g.grupo_id) for g in res.grupos})
    audit["opcoes_saida"] = len(res.grupos)
    audit["vinculos_produto_grupo_saida"] = {
        str(p.codigo): [str(x) for x in (p.grupos or [])]
        for p in (res.itens + res.pizzas)
    }
    audit["vinculos_total_api"] = sum(
        len(v) for v in (audit.get("vinculos_produto_grupo_api") or {}).values()
    )
    audit["vinculos_total_saida"] = sum(
        len(v) for v in (audit.get("vinculos_produto_grupo_saida") or {}).values()
    )

    setattr(res, "_cardapioweb_audit", audit)
    return res

def _cardapioweb_de_respostas(respostas):
    """
    Cardápio Web V4.

    Melhorias desta versão:
    - preserva categoria por contexto pai, category_id e mapa de categorias;
    - opções internas não viram produtos;
    - grupos continuam ligados ao produto pai;
    - deduplicação usa ID estável primeiro e assinatura completa como fallback.
    """
    res = Resultado(origem="Cardápio Web")
    grupos_escritos = set()
    gid_seq = [9900000]

    # Dedupe em duas camadas.
    ids_produto_vistos = set()
    assinaturas_produto_vistas = set()

    GROUP_KEY_RE = re.compile(
        r"(additional|additionals|addon|addons|adicional|adicionais|"
        r"complement|complements|complemento|complementos|"
        r"option|options|opcao|opcoes|modifier|modifiers|"
        r"custom|customs|customization|customizations|"
        r"extra|extras|ingredient|ingredients|ingrediente|ingredientes|"
        r"component|components|componente|componentes|"
        r"choice|choices|variation|variations|variacao|variacoes|"
        r"group|groups|grupo|grupos|item_component|item_components|"
        r"product_option|product_options)",
        re.I,
    )

    PRODUCT_LIST_KEY_RE = re.compile(
        r"^(products|produtos|menu_items|menuitems|items|itens|catalog_items|catalogitems)$",
        re.I,
    )

    CHILD_LIST_RE = re.compile(
        r"(items|itens|options|opcoes|choices|values|products|produtos|"
        r"additionals|addons|complements|complementos|modifiers|extras|"
        r"ingredients|components|children|subitems|sub_items)",
        re.I,
    )

    PRODUCT_HINT_RE = re.compile(
        r"(product|produto|menu_item|menuitem|item_menu|catalog_item|catalogitem)",
        re.I,
    )

    CATEGORY_URL_RE = re.compile(r"(categor|section|secao)", re.I)

    def novo_gid(raw=None):
        if raw not in (None, ""):
            return str(raw)
        gid_seq[0] += 1
        return str(gid_seq[0])

    def norm(v):
        return re.sub(r"\s+", " ", str(v or "").strip()).lower()

    def campo_nome(obj):
        if not isinstance(obj, dict):
            return ""
        for k in ("name", "nome", "title", "titulo", "label"):
            v = obj.get(k)
            if isinstance(v, str) and 1 < len(v.strip()) < 220:
                return v.strip()
        return ""

    def campo_desc(obj):
        if not isinstance(obj, dict):
            return ""
        for k in ("description", "descricao", "subtitle", "subtitulo", "details", "detalhes"):
            v = obj.get(k)
            if isinstance(v, str) and v.strip():
                return texto_seguro(v)
        return ""

    def campo_img(obj):
        if not isinstance(obj, dict):
            return ""
        for k in (
            "image", "imagem", "image_url", "imageUrl", "photo", "foto",
            "picture", "cover", "url_image", "urlImage", "thumbnail"
        ):
            v = obj.get(k)
            if isinstance(v, str):
                v = v.strip()
                if v.startswith("//"):
                    v = "https:" + v
                if v.startswith("http://") or v.startswith("https://"):
                    return imagem_compativel(v)
        return ""

    def preco_com_presenca(obj):
        if not isinstance(obj, dict):
            return False, None
        for k in (
            "price", "preco", "value", "valor", "sale_price", "salePrice",
            "current_price", "currentPrice", "final_price", "finalPrice",
            "unit_price", "unitPrice", "amount", "additional_price",
            "additionalPrice", "extra_price", "extraPrice"
        ):
            if k in obj and obj.get(k) is not None:
                return True, parse_preco(obj.get(k))
        return False, None

    def valor_int(obj, nomes, default):
        for k in nomes:
            if k in obj and obj.get(k) not in (None, ""):
                try:
                    return int(float(obj.get(k)))
                except Exception:
                    pass
        return default

    def get_id(obj):
        if not isinstance(obj, dict):
            return None
        return (
            obj.get("id") or obj.get("uuid") or obj.get("product_id")
            or obj.get("productId") or obj.get("produto_id") or obj.get("produtoId")
            or obj.get("code") or obj.get("codigo")
        )

    def get_category_id(obj):
        if not isinstance(obj, dict):
            return None
        for k in (
            "category_id", "categoryId", "categoria_id", "categoriaId",
            "section_id", "sectionId", "secao_id", "secaoId"
        ):
            if obj.get(k) not in (None, ""):
                return str(obj.get(k))
        cat_obj = obj.get("category") or obj.get("categoria") or obj.get("section") or obj.get("secao")
        if isinstance(cat_obj, dict):
            cid = cat_obj.get("id") or cat_obj.get("uuid") or cat_obj.get("code")
            if cid not in (None, ""):
                return str(cid)
        return None

    def get_category_name_inline(obj):
        if not isinstance(obj, dict):
            return ""
        for k in ("category_name", "categoryName", "categoria_nome", "categoriaNome",
                  "section_name", "sectionName", "secao_nome", "secaoNome"):
            v = obj.get(k)
            if isinstance(v, str) and v.strip():
                return texto_seguro(v)
        cat_obj = obj.get("category") or obj.get("categoria") or obj.get("section") or obj.get("secao")
        if isinstance(cat_obj, dict):
            return texto_seguro(campo_nome(cat_obj))
        if isinstance(cat_obj, str) and cat_obj.strip():
            return texto_seguro(cat_obj)
        return ""

    def listas_filhos(obj):
        out = []
        if not isinstance(obj, dict):
            return out
        for k, v in obj.items():
            if isinstance(v, list) and CHILD_LIST_RE.search(str(k)):
                out.append((str(k), v))
        return out

    def parece_objeto_grupo(obj, chave_pai=""):
        if not isinstance(obj, dict):
            return False
        if GROUP_KEY_RE.search(chave_pai or "") and listas_filhos(obj):
            return True
        selection_keys = {
            "min", "max", "minimum", "maximum", "minimo", "maximo",
            "required", "is_required", "mandatory", "selection_type",
            "select_min", "select_max", "min_quantity", "max_quantity"
        }
        if any(k in obj for k in selection_keys) and listas_filhos(obj):
            return True
        nome = campo_nome(obj).lower()
        if listas_filhos(obj) and re.search(
            r"(ponto|carne|pão|pao|queijo|molho|adicional|complement|"
            r"escolha|opção|opcao|acompanhamento|sabor|borda|massa|tamanho)",
            nome, re.I
        ):
            return True
        return False

    # ------------------------------------------------------------
    # PRÉ-PASSO: mapa de categorias por ID e produto -> categoria
    # ------------------------------------------------------------
    categorias_por_id = {}
    categoria_por_produto_id = {}

    def registrar_categoria(cid, nome):
        if cid not in (None, "") and nome:
            categorias_por_id[str(cid)] = texto_seguro(nome)

    def prepass(obj, url_origem="", categoria_pai=""):
        if isinstance(obj, list):
            for x in obj:
                prepass(x, url_origem, categoria_pai)
            return
        if not isinstance(obj, dict):
            return

        nome = campo_nome(obj)
        tem_preco, _ = preco_com_presenca(obj)
        oid = get_id(obj)

        # Endpoint de categorias: objetos id+nome sem preço são fortes candidatos.
        if CATEGORY_URL_RE.search(url_origem or "") and oid not in (None, "") and nome and not tem_preco:
            registrar_categoria(oid, nome)

        # Objetos que explicitamente carregam uma lista de produtos definem contexto de categoria.
        cat_local = categoria_pai
        if nome and not parece_objeto_grupo(obj):
            for k, v in obj.items():
                if isinstance(v, list) and PRODUCT_LIST_KEY_RE.search(str(k)):
                    # Só considera categoria se houver ao menos um filho com sinais de produto.
                    sinais = 0
                    for child in v[:20]:
                        if isinstance(child, dict):
                            c_tem_preco, _ = preco_com_presenca(child)
                            if c_tem_preco or PRODUCT_HINT_RE.search(str(k)):
                                sinais += 1
                    if sinais:
                        cat_local = texto_seguro(nome)
                        if oid not in (None, ""):
                            registrar_categoria(oid, nome)
                        for child in v:
                            if isinstance(child, dict):
                                pid = get_id(child)
                                if pid not in (None, ""):
                                    categoria_por_produto_id[str(pid)] = cat_local
                        break

        # Relação via category_id explícito.
        cid = get_category_id(obj)
        if oid not in (None, "") and cid:
            # Resolvida depois que mapa estiver completo.
            categoria_por_produto_id.setdefault(str(oid), ("__CID__", cid))

        for k, v in obj.items():
            if isinstance(v, (dict, list)):
                prepass(v, url_origem, cat_local)

    for r in respostas:
        prepass(r.get("data"), r.get("url", ""), "")

    # Resolve placeholders category_id -> nome.
    for pid, valor in list(categoria_por_produto_id.items()):
        if isinstance(valor, tuple) and len(valor) == 2 and valor[0] == "__CID__":
            categoria_por_produto_id[pid] = categorias_por_id.get(valor[1], "")

    # ------------------------------------------------------------
    # GRUPOS
    # ------------------------------------------------------------
    def extrair_opcoes_do_grupo(g, chave_pai=""):
        if not isinstance(g, dict):
            return None, []

        nome_g = campo_nome(g) or str(chave_pai or "Adicionais")
        candidatos = []
        for _, arr in listas_filhos(g):
            for o in arr:
                if not isinstance(o, dict):
                    continue
                oname = campo_nome(o)
                if not oname or parece_objeto_grupo(o):
                    continue
                candidatos.append(o)

        if not candidatos:
            return None, []

        gid = novo_gid(g.get("id") or g.get("uuid") or g.get("code") or g.get("codigo"))
        minimo = valor_int(
            g,
            ("min", "minimum", "minimo", "select_min", "min_quantity"),
            1 if g.get("required") or g.get("is_required") or g.get("mandatory") else 0,
        )
        maximo = valor_int(
            g,
            ("max", "maximum", "maximo", "select_max", "max_quantity"),
            1,
        )
        if maximo < 1:
            maximo = max(1, len(candidatos))

        opcoes = []
        vistos = set()
        for o in candidatos:
            if any(o.get(k) is False for k in ("active", "enabled", "available", "visible")):
                continue
            nome_o = campo_nome(o)
            _, preco_o = preco_com_presenca(o)
            preco_o = float(preco_o or 0.0)
            oid = get_id(o)
            key = str(oid) if oid not in (None, "") else f"{norm(nome_o)}|{preco_o}"
            if key in vistos:
                continue
            vistos.add(key)
            opcoes.append(
                GrupoOpcao(
                    grupo_id=gid,
                    tipo=tipo_grupo(nome_g),
                    grupo_nome=texto_seguro(nome_g),
                    nome=texto_seguro(nome_o),
                    imagem=campo_img(o),
                    preco=preco_o,
                    minimo=minimo,
                    maximo=maximo,
                    repetir=0,
                    metodo_preco=1,
                )
            )
        return gid, opcoes

    def parece_objeto_produto(obj, chave_pai="", dentro_de_grupo=False):
        if dentro_de_grupo or not isinstance(obj, dict):
            return -99
        nome = campo_nome(obj)
        if not nome:
            return -99
        tem_preco, _ = preco_com_presenca(obj)
        if not tem_preco:
            return -99

        score = 0
        keys_lower = {str(k).lower() for k in obj.keys()}

        if PRODUCT_HINT_RE.search(chave_pai or ""):
            score += 3
        if any(k in keys_lower for k in (
            "product_id", "productid", "produto_id", "produtoid", "sku", "slug"
        )):
            score += 3
        if campo_desc(obj):
            score += 2
        if campo_img(obj):
            score += 2
        if get_category_id(obj):
            score += 2
        if get_category_name_inline(obj):
            score += 2
        if any(k in keys_lower for k in (
            "active", "enabled", "available", "visible", "stock",
            "quantity", "is_available", "isactive"
        )):
            score += 1
        if any(GROUP_KEY_RE.search(str(k)) for k in obj.keys()):
            score += 2

        meaningful = [
            k for k in obj.keys()
            if str(k).lower() not in {
                "id", "uuid", "code", "codigo", "name", "nome", "title", "titulo",
                "price", "preco", "value", "valor", "additional_price",
                "additionalprice", "extra_price", "extraprice", "active",
                "enabled", "available", "visible"
            }
        ]
        if len(meaningful) == 0:
            score -= 5
        elif len(meaningful) == 1:
            score -= 2

        if norm(nome) in {
            "delivery", "retirada", "fidelidade", "destaques", "categorias",
            "promoções", "promocoes", "todos", "cardápio", "cardapio"
        }:
            score -= 10

        return score

    def descobrir_grupos_no_produto(prod):
        achados = []
        visitados = set()

        def rec(obj, chave_pai="", depth=0):
            if depth > 8 or not isinstance(obj, (dict, list)):
                return
            oid_py = id(obj)
            if oid_py in visitados:
                return
            visitados.add(oid_py)

            if isinstance(obj, list):
                for x in obj:
                    rec(x, chave_pai, depth + 1)
                return

            if obj is not prod and parece_objeto_produto(obj, chave_pai, False) >= 6:
                return

            if obj is not prod and parece_objeto_grupo(obj, chave_pai):
                gid, opts = extrair_opcoes_do_grupo(obj, chave_pai)
                if gid and opts:
                    achados.append((gid, opts))
                    return

            for k, v in obj.items():
                if not isinstance(v, (dict, list)):
                    continue
                if GROUP_KEY_RE.search(str(k)):
                    if isinstance(v, list):
                        for x in v:
                            if isinstance(x, dict) and parece_objeto_grupo(x, str(k)):
                                gid, opts = extrair_opcoes_do_grupo(x, str(k))
                                if gid and opts:
                                    achados.append((gid, opts))
                                else:
                                    rec(x, str(k), depth + 1)
                            else:
                                rec(x, str(k), depth + 1)
                    elif isinstance(v, dict):
                        if parece_objeto_grupo(v, str(k)):
                            gid, opts = extrair_opcoes_do_grupo(v, str(k))
                            if gid and opts:
                                achados.append((gid, opts))
                            else:
                                rec(v, str(k), depth + 1)
                        else:
                            rec(v, str(k), depth + 1)
                else:
                    rec(v, str(k), depth + 1)

        rec(prod)

        gids = []
        for gid, opts in achados:
            if gid not in grupos_escritos:
                grupos_escritos.add(gid)
                res.grupos.extend(opts)
            if gid not in gids:
                gids.append(gid)
        return gids

    # ------------------------------------------------------------
    # WALK PRINCIPAL
    # ------------------------------------------------------------
    def walk(obj, categoria="", chave_pai="", dentro_de_grupo=False, depth=0):
        if depth > 12:
            return

        if isinstance(obj, list):
            for x in obj:
                walk(x, categoria, chave_pai, dentro_de_grupo, depth + 1)
            return
        if not isinstance(obj, dict):
            return

        if parece_objeto_grupo(obj, chave_pai):
            dentro_de_grupo = True

        nome = campo_nome(obj)
        cat_local = categoria

        # Contexto de categoria pelo pai.
        if nome and not parece_objeto_grupo(obj):
            for k, v in obj.items():
                if isinstance(v, list) and PRODUCT_LIST_KEY_RE.search(str(k)):
                    sinais = 0
                    for child in v[:20]:
                        if isinstance(child, dict):
                            c_tem_preco, _ = preco_com_presenca(child)
                            if c_tem_preco:
                                sinais += 1
                    if sinais:
                        cat_local = texto_seguro(nome)
                        break

        score = parece_objeto_produto(obj, chave_pai, dentro_de_grupo)

        if score >= 3:
            _, preco = preco_com_presenca(obj)
            raw_id = get_id(obj)
            raw_id_s = str(raw_id) if raw_id not in (None, "") else ""

            # Categoria em ordem de confiabilidade.
            categoria_final = get_category_name_inline(obj)
            if not categoria_final and raw_id_s:
                categoria_final = categoria_por_produto_id.get(raw_id_s, "")
            if not categoria_final:
                cid = get_category_id(obj)
                if cid:
                    categoria_final = categorias_por_id.get(cid, "")
            if not categoria_final:
                categoria_final = cat_local or categoria

            desc = campo_desc(obj)
            img = campo_img(obj)

            # Dedupe 1: ID estável.
            if raw_id_s and raw_id_s in ids_produto_vistos:
                return

            # Dedupe 2: assinatura completa. Só remove quando é realmente a mesma entidade.
            assinatura = (
                norm(nome),
                round(float(preco or 0.0), 2),
                norm(categoria_final),
                norm(desc),
                norm(img),
            )
            if assinatura in assinaturas_produto_vistas:
                return

            if raw_id_s:
                ids_produto_vistos.add(raw_id_s)
            assinaturas_produto_vistas.add(assinatura)

            gids = descobrir_grupos_no_produto(obj)

            prod = Produto(
                codigo=raw_id_s or str(len(ids_produto_vistos) + len(assinaturas_produto_vistas)),
                nome=texto_seguro(nome),
                descricao=desc,
                categoria=texto_seguro(categoria_final),
                imagem=img,
                preco=float(preco or 0.0),
                grupos=gids,
                pizza=parece_pizza(nome, categoria_final, desc),
                combo=parece_combo(nome, categoria_final, desc),
            )
            (res.pizzas if prod.pizza and not prod.combo else res.itens).append(prod)
            return

        for k, v in obj.items():
            if not isinstance(v, (dict, list)):
                continue
            prox_grupo = dentro_de_grupo or bool(GROUP_KEY_RE.search(str(k)))
            walk(v, cat_local, str(k), prox_grupo, depth + 1)

    ordenadas = sorted(
        respostas,
        key=lambda r: (
            0 if re.search(r"/(menu|categor|product|produto|item)", r["url"], re.I) else 1,
            len(r["url"]),
        ),
    )

    for r in ordenadas:
        walk(r.get("data"), "", "", False, 0)

    _dedupe_result(res)

    # Remove grupos não utilizados, sem mexer nos vínculos válidos.
    usados = {str(gid) for p in (res.itens + res.pizzas) for gid in p.grupos}
    res.grupos = [g for g in res.grupos if str(g.grupo_id) in usados]

    # Diagnóstico útil para a prévia.
    sem_categoria = sum(1 for p in (res.itens + res.pizzas) if not p.categoria)
    if sem_categoria:
        res.avisos.append(f"{sem_categoria} produto(s) ainda ficaram sem categoria.")
    return res


def _cardapioweb_do_dom(html):
    soup = BeautifulSoup(html or "", "html.parser")
    res = Resultado(origem="Cardápio Web DOM")

    categorias_conhecidas = set()
    for h in soup.find_all(["h1", "h2", "h3", "h4"]):
        t = " ".join(h.stripped_strings).strip()
        if 2 <= len(t) <= 80 and "R$" not in t:
            categorias_conhecidas.add(t)

    candidatos = []
    for node in soup.find_all(["article", "li", "div"]):
        cls = " ".join(node.get("class") or []).lower()
        if not re.search(r"(product|produto|item|card)", cls):
            continue
        txt = " ".join(node.stripped_strings)
        pm = re.search(r"R\$\s*([\d\.,]+)", txt, re.I)
        if not pm:
            continue
        # Rejeita containers gigantes que englobam vários produtos.
        if txt.count("R$") > 2 or len(txt) > 1200:
            continue
        candidatos.append(node)

    vistos = set()
    for node in candidatos:
        name_el = node.find(["h1", "h2", "h3", "h4", "strong"])
        if not name_el:
            continue
        nome = " ".join(name_el.stripped_strings).strip()
        if not nome or nome in categorias_conhecidas or len(nome) > 180:
            continue
        txt = " ".join(node.stripped_strings)
        pm = re.search(r"R\$\s*([\d\.,]+)", txt, re.I)
        preco = parse_preco(pm.group(1)) if pm else 0.0

        categoria = ""
        prev = node.find_previous(["h1", "h2", "h3", "h4"])
        if prev:
            pt = " ".join(prev.stripped_strings).strip()
            if pt != nome and "R$" not in pt and len(pt) <= 100:
                categoria = pt

        img_el = node.find("img")
        img = ""
        if img_el:
            img = (
                img_el.get("src")
                or img_el.get("data-src")
                or img_el.get("data-lazy-src")
                or ""
            )
            if isinstance(img, str) and img.startswith("data:"):
                img = ""

        key = (nome.lower(), round(preco, 2), categoria.lower())
        if key in vistos:
            continue
        vistos.add(key)

        prod = Produto(
            codigo=str(len(vistos)),
            nome=texto_seguro(nome),
            descricao="",
            categoria=texto_seguro(categoria),
            imagem=imagem_compativel(img),
            preco=preco,
            grupos=[],
            pizza=parece_pizza(nome, categoria),
            combo=parece_combo(nome, categoria),
        )
        (res.pizzas if prod.pizza and not prod.combo else res.itens).append(prod)

    _dedupe_result(res)
    return res



# ---------------------------------------------------------------------
# V10 — filtro anti-interface e diagnóstico universal
# ---------------------------------------------------------------------

_UI_EXACT = {
    "categorias", "categoria", "destaques", "promoções", "promocoes",
    "carrinho", "informações da loja", "informacoes da loja",
    "mais informações", "mais informacoes", "programa de pontos",
    "cupons disponíveis pra você", "cupons disponiveis pra voce",
    "cardápio", "cardapio", "menu", "home", "início", "inicio",
    "meus pedidos", "pedido", "pedidos", "finalizar pedido",
    "taxa de entrega", "entrega", "retirada", "buscar", "pesquisar",
}

_UI_PREFIX = (
    "categorias ", "mais informações", "informações da loja",
    "programa de pontos", "cupons ", "carrinho ", "copyright ",
)

def _norm_ui(s):
    return re.sub(r"\s+", " ", str(s or "").strip()).lower()

def _parece_interface(p):
    nome = _norm_ui(getattr(p, "nome", ""))
    desc = _norm_ui(getattr(p, "descricao", ""))
    cat = _norm_ui(getattr(p, "categoria", ""))

    if not nome:
        return True
    if nome in _UI_EXACT:
        return True
    if any(nome.startswith(x) for x in _UI_PREFIX):
        return True
    if len(nome) > 160:
        return True

    # Títulos institucionais / SEO costumam conter estes padrões.
    institucional = (
        "cardápio digital", "cardapio digital", "delivery |",
        "| delivery", " - pedir aqui", "faça seu pedido",
        "faca seu pedido", "a melhor comida da região",
        "a melhor comida da regiao",
    )
    if any(x in nome for x in institucional):
        return True

    # Um registro sem preço, sem imagem, sem categoria e sem grupo é fraco demais.
    sinais = 0
    if float(getattr(p, "preco", 0) or 0) > 0:
        sinais += 1
    if getattr(p, "imagem", ""):
        sinais += 1
    if cat:
        sinais += 1
    if getattr(p, "grupos", None):
        sinais += 1
    if desc and len(desc) >= 8:
        sinais += 1

    if sinais == 0:
        return True

    return False

def limpar_resultado_generico(res, plataforma="Fallback"):
    """
    Filtro conservador. Só é aplicado a HTML/fallback, nunca aos parsers
    específicos que já funcionam (Cardápio Web/InstaDelivery etc.).
    """
    removidos = []
    for attr in ("itens", "pizzas"):
        arr = getattr(res, attr)
        bons = []
        for p in arr:
            if _parece_interface(p):
                removidos.append(p.nome)
            else:
                bons.append(p)
        setattr(res, attr, bons)

    _dedupe_result(res)

    if removidos:
        res.avisos.append(
            f"V10 removeu {len(removidos)} registro(s) que pareciam interface/SEO, não produto."
        )
        setattr(res, "_itens_filtrados_interface", removidos[:200])
    return res


def _classificar_candidato_json(url, content_type, data):
    """
    FINAL:
    - operational: API/SSR com sinais de cardápio;
    - seo: JSON-LD/schema.org, nunca deve encerrar a busca sozinho;
    - telemetry/i18n: candidato deve ser ignorado.
    """
    u = str(url or "").lower()
    ct = str(content_type or "").lower()

    if any(x in u for x in (
        "posthog", "clarity", "sentry", "google-analytics", "googletagmanager",
        "facebook.com/tr", "doubleclick", "/analytics/", "feature-flags",
        "/_i18n/", "/i18n/", "messages.json", "locales/", "translations/"
    )):
        return "ignore"

    if "ld+json" in ct:
        return "seo"

    if isinstance(data, dict):
        ctx = str(data.get("@context") or "").lower()
        tp = str(data.get("@type") or "").lower()
        if "schema.org" in ctx or tp in {
            "restaurant", "localbusiness", "organization",
            "breadcrumblist", "website", "webpage"
        }:
            return "seo"

    if any(x in u for x in ("/api/", "graphql", "internal/", "clientauth/")):
        return "operational"

    return "unknown"


def _score_candidato_v13(url, content_type, summary, data):
    """
    Mantém o score estrutural, mas penaliza JSON-LD/SEO.
    Um JSON SEO pode continuar aparecendo no diagnóstico,
    porém nunca deve vencer um HTML/DOM rico ou uma API operacional.
    """
    base = int((summary or {}).get("score", 0) or 0)
    classe = _classificar_candidato_json(url, content_type, data)

    if classe == "ignore":
        return -999, classe

    if classe == "seo":
        # JSON-LD é útil como pista, mas não como fonte definitiva.
        return max(0, base - 6), classe

    return base, classe


def _html_dom_summary(html):
    soup = BeautifulSoup(html or "", "html.parser")
    texto = soup.get_text(" ", strip=True)
    sinais_preco = len(re.findall(r"R\$\s*\d", texto, re.I))
    imagens_produto = 0
    for img in soup.find_all("img"):
        src = (img.get("src") or img.get("data-src") or img.get("data-original") or "").lower()
        if any(x in src for x in ("produto", "product", "item", "prato", "uploads/produtos", "categorias_produtos")):
            imagens_produto += 1

    cards = soup.select(
        ".item-produto-novo, [data-produto-id], [data-product-id], "
        ".produto, .product, .card-produto, .item-card, "
        "[onclick*='item_name'], [onclick*='product']"
    )

    score = 0
    if sinais_preco >= 3:
        score += 4
    elif sinais_preco:
        score += 2
    if len(cards) >= 3:
        score += 5
    elif cards:
        score += 2
    if imagens_produto >= 3:
        score += 3
    elif imagens_produto:
        score += 1

    return {
        "score": score,
        "sinais_preco": sinais_preco,
        "cards_detectados": len(cards),
        "imagens_produto": imagens_produto,
    }


def _melhor_fonte_diagnostico(diag):
    """
    FINAL: decide a melhor fonte de forma determinística.

    Prioridade:
      1. JSON operacional
      2. JSON estrutural/SSR forte
      3. HTML/DOM rico
      4. JSON SEO apenas como pista
    """
    ranking = diag.get("ranking_json") or []
    dom = diag.get("html_dom") or {}

    operacional = [
        x for x in ranking
        if x.get("candidate_class") == "operational"
        and x.get("score_v17", x.get("score_v17", x.get("score", 0))) > 0
    ]
    if operacional:
        return {"tipo": "json_operacional", "candidato": operacional[0]}

    estruturais = [
        x for x in ranking
        if x.get("candidate_class") not in ("seo", "ignore", "operational")
        and x.get("score_v17", x.get("score_v17", x.get("score", 0))) >= 6
    ]
    if estruturais:
        return {"tipo": "json_estrutural", "candidato": estruturais[0]}

    if dom.get("score", 0) >= 4:
        return {"tipo": "html_dom", "candidato": dom}

    seo = [x for x in ranking if x.get("candidate_class") == "seo"]
    if seo:
        return {"tipo": "json_seo_apenas", "candidato": seo[0]}

    return {"tipo": "nenhuma_fonte_forte", "candidato": None}


def _resumir_json_universal(data):
    info = {
        "tipo_raiz": type(data).__name__,
        "tem_produtos": False,
        "tem_categorias": False,
        "tem_grupos": False,
        "tem_precos": False,
        "tem_imagens": False,
        "chaves_amostra": [],
        "score": 0,
    }
    product_re = re.compile(r"(product|produto|item|menu)", re.I)
    category_re = re.compile(r"(categor|section|secao|grupo)", re.I)
    group_re = re.compile(
        r"(additional|addon|add_on|complement|modifier|option|custom|extra|"
        r"ingredient|choice|variation|subitem|flavor|sabor|topping)",
        re.I,
    )
    price_re = re.compile(r"(price|preco|valor|amount|selling|sale|final)", re.I)
    image_re = re.compile(r"(image|imagem|foto|picture|thumbnail|cover)", re.I)

    seen = set()
    def walk(obj, depth=0):
        if depth > 10:
            return
        oid = id(obj)
        if oid in seen:
            return
        seen.add(oid)

        if isinstance(obj, dict):
            if depth <= 2:
                for k in obj.keys():
                    ks = str(k)
                    if ks not in info["chaves_amostra"] and len(info["chaves_amostra"]) < 60:
                        info["chaves_amostra"].append(ks)
            for k, v in obj.items():
                ks = str(k)
                if product_re.search(ks): info["tem_produtos"] = True
                if category_re.search(ks): info["tem_categorias"] = True
                if group_re.search(ks): info["tem_grupos"] = True
                if price_re.search(ks): info["tem_precos"] = True
                if image_re.search(ks): info["tem_imagens"] = True
                if isinstance(v, (dict, list)):
                    walk(v, depth + 1)
        elif isinstance(obj, list):
            for x in obj[:1500]:
                if isinstance(x, (dict, list)):
                    walk(x, depth + 1)

    walk(data)
    info["score"] = (
        4 * int(info["tem_produtos"]) +
        3 * int(info["tem_grupos"]) +
        2 * int(info["tem_categorias"]) +
        2 * int(info["tem_precos"]) +
        1 * int(info["tem_imagens"])
    )
    return info


def _parece_card_produto_el(el):
    if el is None:
        return False
    try:
        txt = re.sub(r"\s+", " ", el.inner_text(timeout=1500) or "").strip()
    except Exception:
        txt = ""
    if "R$" not in txt:
        return False
    if len(txt) < 4 or len(txt) > 1200:
        return False
    return True


def _resumir_html_interativo(html):
    soup = BeautifulSoup(html or "", "html.parser")
    txt = soup.get_text(" ", strip=True)
    return {
        "tamanho_html": len(html or ""),
        "sinais_preco": len(re.findall(r"R\$\s*\d", txt, re.I)),
        "minimo_maximo": bool(re.search(r"\b(min(?:imo)?|máximo|maximo|escolha\s+\d+)\b", txt, re.I)),
        "palavras_adicionais": bool(re.search(
            r"\b(adicionais?|extras?|complementos?|opções?|opcoes?|sabores?|toppings?|acréscimos?|acrescimos?)\b",
            txt, re.I
        )),
    }


def diagnosticar_interacoes_produtos(url, plataforma=None, max_produtos=6):
    """
    FINAL — abre produtos reais e observa:
    - novas respostas XHR/fetch/document;
    - HTML de modal/detalhe após clique;
    - sinais de adicionais, min/max e opções.

    Não altera o parser. Serve para descobrir de onde vêm adicionais.
    """
    from playwright.sync_api import sync_playwright

    plataforma = plataforma or detectar_plataforma(url) or "Desconhecida"
    resultado = {
        "versao": "FINAL",
        "tipo": "diagnostico_interativo_produtos",
        "plataforma": plataforma,
        "url_solicitada": url,
        "produtos_testados": 0,
        "interacoes": [],
        "erros": [],
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            locale="pt-BR",
            viewport={"width": 1440, "height": 1200},
            user_agent=HEADERS["User-Agent"],
            service_workers="block",
        )
        page = context.new_page()

        respostas = []

        def on_response(resp):
            try:
                ct = (resp.headers.get("content-type") or "").lower()
            except Exception:
                ct = ""
            rtype = str(getattr(resp.request, "resource_type", "") or "").lower()

            low = resp.url.lower()
            if any(x in low for x in (
                "google-analytics", "googletagmanager", "doubleclick",
                "facebook.com/tr", "clarity", "posthog", "sentry",
                "analytics_track", "capi_event"
            )):
                return

            if rtype not in ("xhr", "fetch", "document") and "json" not in ct:
                return

            item = {
                "url": resp.url,
                "status": resp.status,
                "resource_type": rtype,
                "content_type": ct,
                "body_size": None,
                "json_summary": None,
                "body_preview": None,
            }
            try:
                body = resp.body()
                item["body_size"] = len(body)
                if len(body) <= 2_000_000:
                    raw = body.decode("utf-8", errors="replace")
                    if "json" in ct:
                        try:
                            data = json.loads(raw)
                            item["json_summary"] = _resumir_json_universal(data)
                            if item["json_summary"].get("score", 0) > 0 or item["json_summary"].get("tem_grupos"):
                                item["body_preview"] = data
                        except Exception:
                            pass
                    else:
                        # HTML/texto só guarda trecho quando há sinais de adicionais.
                        if re.search(
                            r"(adicion|complement|modifier|option|extra|sabor|topping|min|max|escolha)",
                            raw, re.I
                        ):
                            item["body_preview"] = raw[:12000]
            except Exception:
                pass
            respostas.append(item)

        page.on("response", on_response)
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(1800)

        # scroll para materializar itens
        for frac in (0.3, 0.6, 1.0):
            try:
                page.evaluate(f"window.scrollTo(0, document.body.scrollHeight*{frac})")
                page.wait_for_timeout(300)
            except Exception:
                pass

        # seletores prioritários por plataforma + genéricos
        selectors = []
        if plataforma == "byFood":
            selectors += [
                ".item-produto-novo",
                "[data-produto-id]",
                "[data-product-id]",
                "[onclick*='produto']",
                "[onclick*='product']",
                "img[src*='/produtos/']",
                "img[data-src*='/produtos/']",
            ]
        elif plataforma == "RapidFood":
            selectors += [
                "[onclick*='openProductModal']",
                "[onclick*='produto']",
                "[data-product-id]",
                ".produto",
                ".product",
                "img[src*='uploads/produtos']",
            ]
        selectors += [
            ".produto", ".product", ".card-produto", ".item-card",
            "[class*='produto']", "[class*='product']"
        ]

        candidatos = []
        seen = set()
        for sel in selectors:
            try:
                loc = page.locator(sel)
                count = min(loc.count(), 120)
                for i in range(count):
                    el = loc.nth(i)
                    try:
                        # Se for imagem, sobe para ancestral clicável/card.
                        tag = el.evaluate("(e)=>e.tagName.toLowerCase()")
                        target = el
                        if tag == "img":
                            anc = el.locator("xpath=ancestor::*[@onclick or @data-produto-id or @data-product-id][1]")
                            if anc.count():
                                target = anc.first
                            else:
                                anc2 = el.locator("xpath=ancestor::*[contains(@class,'produto') or contains(@class,'product') or contains(@class,'card')][1]")
                                if anc2.count():
                                    target = anc2.first

                        sig = target.evaluate("(e)=> (e.outerHTML || '').slice(0,1200)")
                        if sig in seen:
                            continue
                        seen.add(sig)

                        if _parece_card_produto_el(target):
                            candidatos.append(target)
                    except Exception:
                        continue
            except Exception:
                continue

        # Tenta no máximo N produtos
        for idx, target in enumerate(candidatos[:max_produtos]):
            antes = len(respostas)
            inter = {
                "indice": idx + 1,
                "texto_card": "",
                "respostas_novas": [],
                "html_apos_clique": None,
                "html_summary": None,
                "erro": None,
            }
            try:
                try:
                    inter["texto_card"] = re.sub(r"\s+", " ", target.inner_text(timeout=1500) or "").strip()[:500]
                except Exception:
                    pass

                target.scroll_into_view_if_needed(timeout=3000)
                page.wait_for_timeout(200)
                try:
                    target.click(timeout=4000)
                except Exception:
                    # fallback JS click
                    target.evaluate("(e)=>e.click()")

                page.wait_for_timeout(1200)

                # captura modal/drawer/dialog/detalhe provável
                html_det = ""
                for sel in (
                    "[role='dialog']", ".modal.show", ".modal.in", ".modal",
                    ".drawer", ".offcanvas.show", ".product-detail", ".produto-detalhe",
                    ".detalhe-produto", ".produto-modal", ".product-modal"
                ):
                    try:
                        loc = page.locator(sel)
                        if loc.count():
                            for j in range(min(loc.count(), 5)):
                                el = loc.nth(j)
                                if el.is_visible():
                                    h = el.inner_html(timeout=2500)
                                    if len(h) > len(html_det):
                                        html_det = h
                    except Exception:
                        pass

                if not html_det:
                    try:
                        html_det = page.content()
                    except Exception:
                        html_det = ""

                if html_det:
                    inter["html_summary"] = _resumir_html_interativo(html_det)
                    # só guarda HTML bruto se houver sinais de adicionais/min-max
                    if inter["html_summary"]["palavras_adicionais"] or inter["html_summary"]["minimo_maximo"]:
                        inter["html_apos_clique"] = html_det[:50000]

                novas = respostas[antes:]
                # mantém apenas respostas úteis
                uteis = []
                for r in novas:
                    js = r.get("json_summary") or {}
                    if js.get("score", 0) > 0 or js.get("tem_grupos") or r.get("body_preview") is not None:
                        uteis.append(r)
                inter["respostas_novas"] = uteis[:30]

                # tenta fechar modal para próximo produto
                for sel in (
                    ".modal.show [data-dismiss='modal']",
                    ".modal.show .close",
                    ".modal.show button[aria-label='Close']",
                    "[role='dialog'] button[aria-label='Close']",
                    ".offcanvas.show .btn-close",
                    ".drawer .close"
                ):
                    try:
                        c = page.locator(sel)
                        if c.count() and c.first.is_visible():
                            c.first.click(timeout=1500)
                            page.wait_for_timeout(250)
                            break
                    except Exception:
                        pass

            except Exception as e:
                inter["erro"] = str(e)

            resultado["interacoes"].append(inter)
            resultado["produtos_testados"] += 1

        browser.close()

    # Resumo final
    encontrou_grupos = False
    encontrou_minmax = False
    respostas_uteis = 0
    for inter in resultado["interacoes"]:
        hs = inter.get("html_summary") or {}
        encontrou_minmax = encontrou_minmax or bool(hs.get("minimo_maximo"))
        for r in inter.get("respostas_novas") or []:
            respostas_uteis += 1
            js = r.get("json_summary") or {}
            encontrou_grupos = encontrou_grupos or bool(js.get("tem_grupos"))

    resultado["resumo"] = {
        "encontrou_grupos_json": encontrou_grupos,
        "encontrou_minmax_html": encontrou_minmax,
        "respostas_uteis": respostas_uteis,
    }
    return resultado



def diagnosticar_rede_universal(url, plataforma=None):
    """
    Observa XHR/fetch/JSON do navegador sem depender do HTML visual.
    Playwright permite acompanhar respostas de rede; aqui guardamos
    metadados de todas e o JSON bruto somente das respostas mais úteis.
    """
    from playwright.sync_api import sync_playwright

    eventos = []
    candidatos = []
    html_final = ""

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            locale="pt-BR",
            viewport={"width": 1440, "height": 1200},
            user_agent=HEADERS["User-Agent"],
            service_workers="block",
        )
        page = context.new_page()

        def on_response(resp):
            evento = {
                "url": resp.url,
                "status": resp.status,
                "method": getattr(resp.request, "method", ""),
                "resource_type": getattr(resp.request, "resource_type", ""),
                "content_type": "",
                "body_size": None,
                "json": False,
                "json_summary": None,
            }
            try:
                evento["content_type"] = resp.headers.get("content-type") or ""
            except Exception:
                pass

            ct = evento["content_type"].lower()
            rtype = str(evento["resource_type"] or "").lower()
            lowurl = resp.url.lower()
            ignorar_candidato = any(x in lowurl for x in (
                "posthog.com","clarity.ms","sentry.io","google-analytics.com",
                "googletagmanager.com","facebook.com/tr","doubleclick.net",
                "/_i18n/","/i18n/","messages.json","locales/","translations/",
                "/analytics/","analytics_track","capi_event","feature-flags","/flags/"
            ))
            pode_json = (not ignorar_candidato) and (
                "json" in ct or
                rtype in ("xhr", "fetch") or
                "/api/" in resp.url.lower() or
                "graphql" in resp.url.lower()
            )

            if pode_json and 200 <= resp.status < 300:
                try:
                    body = resp.body()
                    evento["body_size"] = len(body)
                    if len(body) <= 5_000_000:
                        data = json.loads(body.decode("utf-8", errors="replace"))
                        summary = _resumir_json_universal(data)
                        evento["json"] = True
                        evento["json_summary"] = summary
                        score_v17, candidate_class = _score_candidato_v13(
                            resp.url, evento["content_type"], summary, data
                        )
                        evento["candidate_class"] = candidate_class
                        evento["score_v17"] = score_v17
                        if score_v17 > 0:
                            candidatos.append({
                                "url": resp.url,
                                "status": resp.status,
                                "method": evento["method"],
                                "resource_type": evento["resource_type"],
                                "content_type": evento["content_type"],
                                "body_size": len(body),
                                "score": summary["score"],
                                "score_v17": score_v17,
                                "candidate_class": candidate_class,
                                "json_summary": summary,
                                "data": data,
                            })
                except Exception:
                    pass

            eventos.append(evento)

        page.on("response", on_response)
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(2500)

        # Scroll progressivo para disparar lazy-loading/XHR.
        for frac in (0.25, 0.5, 0.75, 1.0):
            try:
                page.evaluate(f"window.scrollTo(0, document.body.scrollHeight*{frac})")
                page.wait_for_timeout(450)
            except Exception:
                pass
        page.wait_for_timeout(700)

        try:
            titulo = page.title()
            url_final = page.url
        except Exception:
            titulo = ""
            url_final = url

        # FINAL: também examina payloads SSR/Nuxt/Next embutidos no HTML.
        try:
            html_final = page.content()
            soup_diag = BeautifulSoup(html_final, "html.parser")
            for idx, sc in enumerate(soup_diag.find_all("script")):
                stype = (sc.get("type") or "").lower()
                sid = (sc.get("id") or "").lower()
                raw = (sc.string or sc.get_text() or "").strip()
                if not raw or len(raw) > 8_000_000:
                    continue
                cand = None
                origem_ssr = None

                if "json" in stype or sid in ("__next_data__","__nuxt_data__","__nuxt__"):
                    try:
                        cand = json.loads(raw)
                        origem_ssr = f"inline-script:{sid or stype or idx}"
                    except Exception:
                        pass

                # Nuxt antigo: window.__NUXT__ = {...}
                if cand is None and "__NUXT__" in raw and len(raw) < 2_000_000:
                    mnuxt = re.search(r"(?:window\.)?__NUXT__\s*=\s*(\{.*\})\s*;?\s*$", raw, re.S)
                    if mnuxt:
                        try:
                            cand = json.loads(mnuxt.group(1))
                            origem_ssr = "inline-window.__NUXT__"
                        except Exception:
                            pass

                if cand is not None:
                    summary = _resumir_json_universal(cand)
                    score_v17, candidate_class = _score_candidato_v13(
                        origem_ssr, stype or "application/json", summary, cand
                    )
                    if score_v17 > 0:
                        candidatos.append({
                            "url": origem_ssr,
                            "status": 200,
                            "method": "INLINE",
                            "resource_type": "ssr",
                            "content_type": stype or "application/json",
                            "body_size": len(raw.encode("utf-8",errors="ignore")),
                            "score": summary["score"],
                            "score_v17": score_v17,
                            "candidate_class": candidate_class,
                            "json_summary": summary,
                            "data": cand,
                        })
        except Exception:
            pass

        browser.close()

    # Deduplica candidatos por URL + assinatura básica e limita RAW.
    unicos = {}
    for c in candidatos:
        key = (c["url"], c["status"], c["body_size"])
        atual = unicos.get(key)
        if atual is None or c["score"] > atual["score"]:
            unicos[key] = c

    ranking = sorted(
        unicos.values(),
        key=lambda x: (
            x.get("score_v17", x.get("score", 0)),
            1 if x.get("candidate_class") == "operational" else 0,
            x.get("body_size") or 0
        ),
        reverse=True,
    )

    # Mantém JSON bruto dos 12 melhores; nos demais, só metadados.
    ranking_export = []
    for i, c in enumerate(ranking[:40]):
        item = dict(c)
        if i >= 12:
            item.pop("data", None)
        ranking_export.append(item)

    return {
        "versao": "FINAL",
        "tipo": "diagnostico_universal_v17",
        "plataforma": plataforma or detectar_plataforma(url) or "Desconhecida",
        "url_solicitada": url,
        "url_final": url_final,
        "titulo_pagina": titulo,
        "gerado_em": datetime.now().isoformat(timespec="seconds"),
        "total_respostas_observadas": len(eventos),
        "total_json_candidatos": len(ranking),
        "ranking_json": ranking_export,
        "html_dom": _html_dom_summary(html_final),
        "melhor_fonte": None,
        "eventos": eventos[:1000],
    }


def interpretar_html(html, origem="HTML Universal"):
    soup = BeautifulSoup(html or "", "html.parser")
    res = Resultado(origem=origem)

    # JSON-LD
    for s in soup.find_all("script", attrs={"type": re.compile("json", re.I)}):
        txt = s.get_text(strip=True)
        if not txt:
            continue
        try:
            data=json.loads(txt)
        except Exception:
            continue
        for p in _produtos_json(data):
            _append_prod(res, p)

    # Produto individual via OpenGraph + preço visível
    title = _meta(soup, "og:title") or (soup.title.get_text(" ", strip=True) if soup.title else "")
    desc = _meta(soup, "og:description") or _meta(soup, "description")
    img = _meta(soup, "og:image")
    bodytxt = soup.get_text(" ", strip=True)
    pm = re.search(r"R\$\s*([\d\.,]+)", bodytxt, re.I)
    if title and pm:
        clean = re.sub(r"\s+-\s+[^-]+(?:\s+-\s+Pedir aqui)?$", "", title).strip()
        _append_prod(res, {
            "name": clean, "description": desc, "image": img,
            "price": parse_preco(pm.group(1)), "category": ""
        })

    # Cards visíveis genéricos
    for node in soup.find_all(["article","li","div"], limit=4000):
        txt = " ".join(node.stripped_strings)
        pm = re.search(r"R\$\s*([\d\.,]+)", txt, re.I)
        if not pm:
            continue
        name_el = node.find(["h1","h2","h3","h4","strong"])
        if not name_el:
            continue
        nome = name_el.get_text(" ", strip=True)
        if len(nome) < 2 or len(nome) > 180:
            continue
        img_el = node.find("img")
        _append_prod(res, {
            "name": nome,
            "description": "",
            "image": (img_el.get("src") if img_el else ""),
            "price": parse_preco(pm.group(1)),
            "category": ""
        })

    _dedupe_result(res)
    return res

def _meta(soup, key):
    el=soup.find("meta", attrs={"property":key}) or soup.find("meta", attrs={"name":key})
    return (el.get("content") or "").strip() if el else ""

def _produtos_json(obj, cat=""):
    out=[]
    if isinstance(obj,list):
        for x in obj: out.extend(_produtos_json(x,cat))
    elif isinstance(obj,dict):
        local=cat
        if (obj.get("name") or obj.get("title")) and any(k in obj for k in ("items","products")):
            local=obj.get("name") or obj.get("title")
        name=obj.get("name") or obj.get("title")
        price=obj.get("price") or obj.get("value")
        if name and price is not None and not any(k in obj for k in ("items","products","categories")):
            out.append({
                "name":name,"description":obj.get("description") or "",
                "image":obj.get("image") or obj.get("imageUrl") or "",
                "price":parse_preco(price),"category":local
            })
        for v in obj.values():
            if isinstance(v,(dict,list)):
                out.extend(_produtos_json(v,local))
    return out

def _append_prod(res, p):
    nome=texto_seguro(p.get("name"))
    if not nome:
        return
    cat=texto_seguro(p.get("category"))
    desc=texto_seguro(p.get("description"))
    prod=Produto(
        codigo=str(len(res.itens)+len(res.pizzas)+1),
        nome=nome,descricao=desc,categoria=cat,
        imagem=imagem_compativel(p.get("image")),
        preco=parse_preco(p.get("price")),
        grupos=[],
        pizza=parece_pizza(nome,cat,desc),
        combo=parece_combo(nome,cat,desc)
    )
    (res.pizzas if prod.pizza and not prod.combo else res.itens).append(prod)

def _dedupe_result(res):
    for attr in ("itens","pizzas"):
        arr=getattr(res,attr); seen=set(); out=[]
        for p in arr:
            k=(p.nome.lower(),round(p.preco,2),p.categoria.lower())
            if k in seen: continue
            seen.add(k); out.append(p)
        setattr(res,attr,out)

def render_playwright(url):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        context=browser.new_context(
            locale="pt-BR",
            viewport={"width":1440,"height":1200},
            user_agent=HEADERS["User-Agent"],
            service_workers="block",
        )
        page=context.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(1800)
        for frac in (0.33,0.66,1.0):
            try:
                page.evaluate(f"window.scrollTo(0, document.body.scrollHeight*{frac})")
                page.wait_for_timeout(350)
            except Exception:
                pass
        html=page.content()
        browser.close()
        return html
