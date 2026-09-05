"""Enriquecimento conservador do Resultado Brendi usando o __NUXT_DATA__ comprovado.

A rotina só associa sabores quando há correspondência exata de nome entre um
Produto já lido pelo parser oficial e um tamanho ativo da categoria de pizza.
Não cria produtos novos, não altera produtos sem correspondência e não usa
heurística de categoria/nome aproximado.
"""
from __future__ import annotations

import json
import re
from bs4 import BeautifulSoup

from brendi_nuxt_parser import extrair_pizzas_brendi_nuxt
from models import GrupoOpcao
from utils import imagem_compativel, texto_seguro


def _norm(value):
    return re.sub(r"\s+", " ", str(value or "").strip()).casefold()


def _preco_por_slug(flavor, size_slug):
    for item in flavor.get("prices") or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("slug") or "") != str(size_slug or ""):
            continue
        try:
            return float(item.get("price") or 0) / 100.0
        except Exception:
            return None
    return None


def enriquecer_resultado_brendi_nuxt(resultado, nuxt_data):
    """Liga sabores/tamanhos Brendi ao Resultado existente de forma fail-closed."""
    estrutura = extrair_pizzas_brendi_nuxt(nuxt_data)
    produtos = list(getattr(resultado, "itens", []) or []) + list(getattr(resultado, "pizzas", []) or [])
    por_nome = {}
    for produto in produtos:
        chave = _norm(getattr(produto, "nome", ""))
        if chave:
            por_nome.setdefault(chave, []).append(produto)

    grupos_existentes = {str(g.grupo_id) for g in (getattr(resultado, "grupos", []) or [])}
    vinculados = 0
    opcoes = 0

    for categoria in estrutura.get("categories") or []:
        cat_id = str(categoria.get("id") or "")
        sabores = estrutura.get("flavorsByCategory", {}).get(cat_id) or []
        if not cat_id or not sabores:
            continue

        metodo = 3 if str(categoria.get("calculateType") or "").lower() == "max" else 1
        for tamanho in categoria.get("sizes") or []:
            if not isinstance(tamanho, dict) or tamanho.get("active") is False:
                continue
            nome_tamanho = str(tamanho.get("name") or "").strip()
            slug_tamanho = str(tamanho.get("slug") or "").strip()
            candidatos = por_nome.get(_norm(nome_tamanho)) or []
            # Correspondência ambígua não é materializada.
            if len(candidatos) != 1 or not slug_tamanho:
                continue

            numeros = []
            for n in tamanho.get("numOfFlavors") or []:
                try:
                    n = int(n)
                except Exception:
                    continue
                if n > 0:
                    numeros.append(n)
            if not numeros:
                continue
            minimo = min(numeros)
            maximo = max(numeros)

            validos = []
            vistos = set()
            for sabor in sabores:
                if not isinstance(sabor, dict) or sabor.get("active") is False:
                    continue
                nome = texto_seguro(sabor.get("name") or "")
                preco = _preco_por_slug(sabor, slug_tamanho)
                if not nome or preco is None:
                    continue
                chave = (_norm(nome), round(float(preco), 6))
                if chave in vistos:
                    continue
                vistos.add(chave)
                validos.append((sabor, nome, preco))
            if not validos:
                continue

            gid = f"brendi-pizza-{cat_id}-{slug_tamanho}"
            produto = candidatos[0]
            if gid not in produto.grupos:
                produto.grupos.append(gid)
            produto.pizza = True
            produto.metodo_preco_pizza = metodo
            vinculados += 1

            if gid not in grupos_existentes:
                for sabor, nome, preco in validos:
                    resultado.grupos.append(GrupoOpcao(
                        grupo_id=gid,
                        tipo=2,
                        grupo_nome="Sabores",
                        nome=nome,
                        imagem=imagem_compativel(sabor.get("picture") or ""),
                        preco=preco,
                        minimo=minimo,
                        maximo=maximo,
                        repetir=0,
                        metodo_preco=metodo,
                    ))
                    opcoes += 1
                grupos_existentes.add(gid)

    if vinculados:
        resultado.origem = (str(getattr(resultado, "origem", "") or "Brendi") + " + Nuxt pizzas").strip()
    return resultado, {"produtos_vinculados": vinculados, "opcoes_materializadas": opcoes}


def extrair_nuxt_data_html(html):
    soup = BeautifulSoup(html or "", "html.parser")
    script = soup.find("script", id="__NUXT_DATA__")
    if not script:
        raise ValueError("Brendi: __NUXT_DATA__ não encontrado na página pública.")
    raw = (script.string or script.get_text() or "").strip()
    if not raw:
        raise ValueError("Brendi: __NUXT_DATA__ vazio.")
    data = json.loads(raw)
    if not isinstance(data, list):
        raise ValueError("Brendi: __NUXT_DATA__ em formato inesperado.")
    return data
