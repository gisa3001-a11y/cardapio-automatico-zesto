"""Enriquecimento conservador de variantes nomeadas da Ola Click.

A fonte Nuxt publica ``product_variants`` para todos os produtos. Variantes únicas
sem nome representam apenas o preço normal e não viram adicionais. Somente quando
um produto possui duas ou mais variantes nomeadas, a escolha é materializada como
grupo obrigatório 1/1. O preço-base vira o menor preço real entre as variantes e
cada opção recebe apenas o delta para esse preço, preservando o valor final sem
duplicação.
"""
import json
import re
from html import unescape

from models import GrupoOpcao, Resultado


def _decode_nuxt(root):
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
            if len(v) == 2 and v[0] == "EmptyRef":
                return None
            return [ref(x) for x in v]
        if isinstance(v, dict):
            return {k: ref(x) for k, x in v.items()}
        return v

    return resolve(0)


def extrair_nuxt_data_html(html: str):
    m = re.search(
        r'<script[^>]+id=["\']__NUXT_DATA__["\'][^>]*>(.*?)</script>',
        html or "",
        flags=re.I | re.S,
    )
    if not m:
        raise ValueError("Ola Click: __NUXT_DATA__ não encontrado.")
    raw = unescape(m.group(1).strip())
    return json.loads(raw)


def _produtos_nuxt(raw):
    decoded = _decode_nuxt(raw)
    try:
        store = decoded["pinia"]["productsCategories"]
        cats = store.get("productsCategories") or store.get("originalProductsCategories") or []
    except Exception as exc:
        raise ValueError("Ola Click: productsCategories não encontrado no __NUXT_DATA__.") from exc

    out = {}
    for cat in cats:
        if not isinstance(cat, dict) or cat.get("visible") is False:
            continue
        if str(cat.get("type") or "").upper() == "FAVORITE":
            continue
        for p in cat.get("products") or []:
            if not isinstance(p, dict) or p.get("visible") is False:
                continue
            pid = str(p.get("id") or "")
            if pid and pid not in out:
                out[pid] = p
    return out


def enriquecer_resultado_olaclick_variantes(resultado: Resultado, raw):
    """Materializa apenas variantes inequivocamente selecionáveis.

    Retorna ``(resultado, auditoria)`` e modifica o próprio resultado recebido.
    """
    mapa = _produtos_nuxt(raw)
    auditoria = {
        "produtos_nuxt": len(mapa),
        "produtos_vinculados": 0,
        "opcoes_materializadas": 0,
    }
    grupos_existentes = {str(g.grupo_id) for g in resultado.grupos}

    for prod in list(resultado.itens) + list(resultado.pizzas):
        p = mapa.get(str(prod.codigo or ""))
        if not isinstance(p, dict):
            continue
        variants = [v for v in (p.get("product_variants") or []) if isinstance(v, dict)]
        nomeadas = []
        for v in variants:
            nome = str(v.get("name") or "").strip()
            if not nome:
                continue
            try:
                centavos = int(v.get("price"))
            except Exception:
                continue
            if centavos < 0:
                continue
            nomeadas.append((v, nome, centavos / 100.0))

        # Uma variante isolada não prova uma escolha. Duas ou mais nomeadas, sim.
        if len(nomeadas) < 2:
            continue

        base = min(preco for _, _, preco in nomeadas)
        gid = f"olaclick-variant-{prod.codigo}"
        if gid not in prod.grupos:
            prod.grupos.append(gid)
        prod.preco = base

        if gid not in grupos_existentes:
            for _, nome, preco_final in nomeadas:
                resultado.grupos.append(
                    GrupoOpcao(
                        grupo_id=gid,
                        tipo=1,
                        grupo_nome="Variação",
                        nome=nome,
                        preco=max(0.0, round(preco_final - base, 2)),
                        minimo=1,
                        maximo=1,
                        repetir=0,
                        metodo_preco=1,
                    )
                )
                auditoria["opcoes_materializadas"] += 1
            grupos_existentes.add(gid)
        else:
            auditoria["opcoes_materializadas"] += sum(1 for g in resultado.grupos if str(g.grupo_id) == gid)

        auditoria["produtos_vinculados"] += 1

    return resultado, auditoria
