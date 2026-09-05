"""Enriquecimento conservador do Resultado Brendi usando o __NUXT_DATA__ comprovado.

A rotina prioriza associação exata com produtos já lidos. Quando a própria fonte
Nuxt declara inequivocamente uma categoria de pizza, um tamanho ativo e sabores
com preço para aquele tamanho, mas o parser oficial não expõe esse tamanho como
produto, a rotina pode materializar o tamanho como pizza. Não associa sabores a
combos por aproximação de nome.
"""
from __future__ import annotations

import json
import re
from bs4 import BeautifulSoup

from brendi_nuxt_parser import extrair_pizzas_brendi_nuxt
from models import GrupoOpcao, Produto
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


def _categoria_pizza_explicita(categoria):
    principal = _norm(categoria.get("mainCategory"))
    nome = _norm(categoria.get("name"))
    return principal == "pizza" or nome.startswith("pizza") or nome.startswith("pizzas")


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
    criados = 0
    opcoes = 0
    tamanhos_ativos = []
    correspondencias = []

    for categoria in estrutura.get("categories") or []:
        cat_id = str(categoria.get("id") or "")
        sabores = estrutura.get("flavorsByCategory", {}).get(cat_id) or []
        if not cat_id or not sabores:
            continue

        metodo = 3 if str(categoria.get("calculateType") or "").lower() == "max" else 1
        categoria_pizza = _categoria_pizza_explicita(categoria)
        for tamanho in categoria.get("sizes") or []:
            if not isinstance(tamanho, dict) or tamanho.get("active") is False:
                continue
            nome_tamanho = str(tamanho.get("name") or "").strip()
            slug_tamanho = str(tamanho.get("slug") or "").strip()
            if nome_tamanho:
                tamanhos_ativos.append({
                    "categoria": str(categoria.get("name") or ""),
                    "categoria_id": cat_id,
                    "nome": nome_tamanho,
                    "slug": slug_tamanho,
                })
            candidatos = por_nome.get(_norm(nome_tamanho)) or []
            correspondencias.append({
                "categoria": str(categoria.get("name") or ""),
                "tamanho": nome_tamanho,
                "slug": slug_tamanho,
                "candidatos_exatos": len(candidatos),
                "nomes_candidatos": [str(getattr(p, "nome", "") or "") for p in candidatos],
            })
            if len(candidatos) > 1 or not slug_tamanho or not nome_tamanho:
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

            produto = candidatos[0] if len(candidatos) == 1 else None
            if produto is None:
                # Só cria um tamanho ausente quando a fonte comprova explicitamente
                # que se trata de pizza e possui sabores precificados para o slug.
                if not categoria_pizza:
                    continue
                produto = Produto(
                    codigo=f"brendi-size-{cat_id}-{slug_tamanho}",
                    nome=texto_seguro(nome_tamanho),
                    categoria=texto_seguro(categoria.get("name") or "Pizzas"),
                    preco=0.0,
                    pizza=True,
                    metodo_preco_pizza=metodo,
                )
                resultado.pizzas.append(produto)
                produtos.append(produto)
                por_nome.setdefault(_norm(nome_tamanho), []).append(produto)
                criados += 1

            gid = f"brendi-pizza-{cat_id}-{slug_tamanho}"
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
    auditoria = {
        "produtos_vinculados": vinculados,
        "produtos_criados": criados,
        "opcoes_materializadas": opcoes,
        "produtos_lidos": [
            {
                "nome": str(getattr(p, "nome", "") or ""),
                "categoria": str(getattr(p, "categoria", "") or ""),
                "pizza": bool(getattr(p, "pizza", False)),
            }
            for p in produtos
        ],
        "tamanhos_ativos": tamanhos_ativos,
        "correspondencias": correspondencias,
    }
    return resultado, auditoria


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
