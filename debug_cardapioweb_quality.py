"""Auditoria somente-leitura da loja real Cardapio Web usada pela bateria V2.

Compara o endpoint oficial de categorias capturado pelo parser com o Resultado
materializado pelo proprio parser. Nao altera producao. Procura regressao em
cobertura, categorias, precos, fotos, adicionais/vinculos, duplicidades e pizzas.
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from fetchers import buscar_cardapioweb
from utils import parse_preco, parece_pizza

STORE_URL = "https://app.cardapioweb.com/shakepoint_westplaza"
OUT = Path("artifacts/cardapioweb_quality.json")


def _norm(v: Any) -> str:
    return re.sub(r"\s+", " ", str(v or "").strip()).lower()


def _ativo(obj: Any) -> bool:
    if not isinstance(obj, dict):
        return False
    status = str(obj.get("status") or "ACTIVE").strip().upper()
    if status in {"INACTIVE", "DISABLED", "HIDDEN", "DELETED"}:
        return False
    for k in ("active", "enabled", "available", "visible", "is_active", "isActive"):
        if k in obj and obj.get(k) is False:
            return False
    return True


def _nome(obj: dict[str, Any]) -> str:
    for k in ("name", "nome", "title", "titulo", "label"):
        v = obj.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _descricao(obj: dict[str, Any]) -> str:
    for k in ("description", "descricao", "subtitle", "subtitulo", "details", "detalhes"):
        v = obj.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _imagem(obj: dict[str, Any]) -> str:
    for k in ("image_url", "imageUrl", "thumbnail_url", "thumbnailUrl", "photo", "foto", "picture", "cover", "url_image", "urlImage"):
        v = obj.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    im = obj.get("image") or obj.get("imagem")
    if isinstance(im, dict):
        for k in ("image_url", "imageUrl", "thumbnail_url", "thumbnailUrl", "url"):
            v = im.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
    if isinstance(im, str) and im.strip():
        return im.strip()
    return ""


def _preco_produto(obj: dict[str, Any]) -> float:
    for k in ("price", "preco", "selling_price", "sellingPrice", "value", "valor"):
        if k in obj and obj.get(k) is not None:
            return float(parse_preco(obj.get(k)))
    return 0.0


def _preco_opcao(obj: dict[str, Any]) -> float:
    for k in ("price", "additional_price", "additionalPrice", "extra_price", "extraPrice", "value", "valor"):
        if k in obj and obj.get(k) is not None:
            return float(parse_preco(obj.get(k)))
    return 0.0


def _sub_key(obj: dict[str, Any]) -> str:
    sid = obj.get("id")
    if sid not in (None, ""):
        return str(sid)
    return f"sig:{_norm(_nome(obj))}|{_preco_opcao(obj):.6f}|{_norm(_imagem(obj))}"


def main() -> int:
    resultado = buscar_cardapioweb(STORE_URL, diagnostico=True)
    diag = getattr(resultado, "_diagnostico_rede", {}) or {}
    categories = diag.get("categories_raw")
    if not isinstance(categories, list):
        raise SystemExit("Cardapio Web: endpoint oficial de categorias nao foi capturado.")

    produtos = list(resultado.itens or []) + list(resultado.pizzas or [])
    por_id = {str(p.codigo): p for p in produtos if getattr(p, "codigo", None) not in (None, "")}

    raw_ids: Counter[str] = Counter()
    semanticos: Counter[tuple[str, str]] = Counter()
    raw_produtos: dict[str, dict[str, Any]] = {}
    raw_fotos = 0
    raw_precos_zero = 0
    raw_vinculos: set[tuple[str, str]] = set()
    raw_grupos_assinaturas: dict[str, set[tuple[Any, ...]]] = defaultdict(set)
    raw_opcoes: dict[tuple[str, str], dict[str, Any]] = {}
    categorias_ativas = 0

    for cat in categories:
        if not isinstance(cat, dict) or not _ativo(cat):
            continue
        categorias_ativas += 1
        categoria = _nome(cat)
        for item in cat.get("items") or []:
            if not isinstance(item, dict) or not _ativo(item):
                continue
            nome = _nome(item)
            if not nome:
                continue
            pid = str(item.get("id") or "")
            raw_ids[pid] += 1
            semanticos[(_norm(nome), _norm(categoria))] += 1
            img = _imagem(item)
            preco = _preco_produto(item)
            if img:
                raw_fotos += 1
            if preco == 0:
                raw_precos_zero += 1
            raw_produtos[pid] = {
                "nome": nome,
                "categoria": categoria,
                "descricao": _descricao(item),
                "preco": preco,
                "imagem": img,
                "grupos": [],
            }

            for g in item.get("add_ons") or []:
                if not isinstance(g, dict) or not _ativo(g) or g.get("id") in (None, ""):
                    continue
                gid = str(g.get("id"))
                subs = [s for s in (g.get("subitems") or []) if isinstance(s, dict) and _ativo(s) and _nome(s)]
                if not subs:
                    continue
                raw_vinculos.add((pid, gid))
                if gid not in raw_produtos[pid]["grupos"]:
                    raw_produtos[pid]["grupos"].append(gid)
                assinatura = (
                    _norm(_nome(g)),
                    int(float(g.get("minimum_quantity") or g.get("minimum") or g.get("min") or 0)),
                    int(float(g.get("maximum_quantity") or g.get("maximum") or g.get("max") or 1)),
                    tuple((_sub_key(s), _norm(_nome(s)), round(_preco_opcao(s), 6), bool(_imagem(s))) for s in subs),
                )
                raw_grupos_assinaturas[gid].add(assinatura)
                for s in subs:
                    raw_opcoes[(gid, _sub_key(s))] = {
                        "nome": _nome(s),
                        "preco": _preco_opcao(s),
                        "imagem": _imagem(s),
                    }

    converted_links = {(str(p.codigo), str(gid)) for p in produtos for gid in (p.grupos or [])}
    converted_options_by_group: dict[str, list[Any]] = defaultdict(list)
    for o in resultado.grupos or []:
        converted_options_by_group[str(o.grupo_id)].append(o)

    produtos_ausentes = sorted(pid for pid in raw_produtos if pid and pid not in por_id)
    produtos_extras = sorted(pid for pid in por_id if pid and pid not in raw_produtos)
    divergencias_produto: list[dict[str, Any]] = []
    classificacoes_pizza: list[dict[str, Any]] = []

    for pid, raw in raw_produtos.items():
        p = por_id.get(pid)
        if p is None:
            continue
        diffs = {}
        if _norm(p.nome) != _norm(raw["nome"]):
            diffs["nome"] = [raw["nome"], p.nome]
        if _norm(p.categoria) != _norm(raw["categoria"]):
            diffs["categoria"] = [raw["categoria"], p.categoria]
        if abs(float(p.preco or 0) - float(raw["preco"])) > 0.001:
            diffs["preco"] = [raw["preco"], float(p.preco or 0)]
        if bool(raw["imagem"]) != bool(p.imagem):
            diffs["imagem_presenca"] = [bool(raw["imagem"]), bool(p.imagem)]
        if sorted(str(x) for x in raw["grupos"]) != sorted(str(x) for x in (p.grupos or [])):
            diffs["grupos"] = [sorted(raw["grupos"]), sorted(str(x) for x in (p.grupos or []))]
        if diffs:
            divergencias_produto.append({"id": pid, "nome": raw["nome"], "divergencias": diffs})

        semantica = bool(parece_pizza(raw["nome"], raw["categoria"], raw["descricao"]))
        if bool(getattr(p, "pizza", False)) != semantica:
            classificacoes_pizza.append({
                "id": pid,
                "nome": raw["nome"],
                "categoria": raw["categoria"],
                "parser_pizza": bool(getattr(p, "pizza", False)),
                "semantica_pizza": semantica,
            })

    opcoes_divergentes: list[dict[str, Any]] = []
    raw_option_count_by_group = Counter(gid for gid, _ in raw_opcoes)
    for gid, expected_count in raw_option_count_by_group.items():
        saida = converted_options_by_group.get(gid, [])
        if len(saida) != expected_count:
            opcoes_divergentes.append({"grupo_id": gid, "raw": expected_count, "saida": len(saida), "tipo": "contagem"})
            continue
        raw_sig = Counter((_norm(v["nome"]), round(float(v["preco"]), 6), bool(v["imagem"])) for (g, _), v in raw_opcoes.items() if g == gid)
        out_sig = Counter((_norm(o.nome), round(float(o.preco or 0), 6), bool(o.imagem)) for o in saida)
        if raw_sig != out_sig:
            opcoes_divergentes.append({"grupo_id": gid, "tipo": "conteudo", "raw": list(raw_sig.elements()), "saida": list(out_sig.elements())})

    audit_interna = getattr(resultado, "_cardapioweb_audit", {}) or {}
    payload = {
        "url": STORE_URL,
        "fonte": diag.get("fonte_principal"),
        "categorias_ativas": categorias_ativas,
        "raw_produtos": len(raw_produtos),
        "saida_produtos": len(produtos),
        "raw_produtos_com_foto": raw_fotos,
        "saida_produtos_com_foto": sum(1 for p in produtos if p.imagem),
        "raw_precos_zero": raw_precos_zero,
        "saida_precos_zero": sum(1 for p in produtos if float(p.preco or 0) == 0),
        "raw_grupos_unicos": len(raw_grupos_assinaturas),
        "saida_grupos_unicos": len(converted_options_by_group),
        "raw_opcoes_unicas_por_grupo": len(raw_opcoes),
        "saida_opcoes": len(resultado.grupos or []),
        "raw_vinculos": len(raw_vinculos),
        "saida_vinculos": len(converted_links),
        "raw_pizzas_semanticas": sum(1 for r in raw_produtos.values() if parece_pizza(r["nome"], r["categoria"], r["descricao"])),
        "saida_pizzas": len(resultado.pizzas or []),
        "produtos_ausentes": produtos_ausentes,
        "produtos_extras": produtos_extras,
        "ids_produto_duplicados": {k: n for k, n in raw_ids.items() if k and n > 1},
        "duplicidades_semanticas_nome_categoria": {repr(k): n for k, n in semanticos.items() if n > 1},
        "grupos_com_mesmo_id_e_configuracoes_diferentes": {gid: len(sigs) for gid, sigs in raw_grupos_assinaturas.items() if len(sigs) > 1},
        "vinculos_raw_nao_preservados": sorted([list(x) for x in raw_vinculos - converted_links]),
        "vinculos_extras_saida": sorted([list(x) for x in converted_links - raw_vinculos]),
        "divergencias_produto": divergencias_produto,
        "divergencias_opcoes": opcoes_divergentes,
        "divergencias_classificacao_pizza": classificacoes_pizza,
        "auditoria_interna_parser": audit_interna,
    }

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({
        "produtos": payload["saida_produtos"],
        "fotos": payload["saida_produtos_com_foto"],
        "grupos": payload["saida_grupos_unicos"],
        "opcoes": payload["saida_opcoes"],
        "vinculos": payload["saida_vinculos"],
        "pizzas": payload["saida_pizzas"],
        "ausentes": len(produtos_ausentes),
        "divergencias_produto": len(divergencias_produto),
        "divergencias_opcoes": len(opcoes_divergentes),
        "conflitos_grupo": len(payload["grupos_com_mesmo_id_e_configuracoes_diferentes"]),
        "divergencias_pizza": len(classificacoes_pizza),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
