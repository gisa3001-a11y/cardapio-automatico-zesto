"""Diagnostico temporario de endpoints JSON para casos ainda sem produtos na V2.

Nao armazena o cardapio completo. Registra apenas estrutura, caminhos de listas,
chaves de amostras e resumos especificos para orientar adaptadores.
"""
import json
from pathlib import Path
from typing import Any, Dict, List

from browser_probe import coletar_json_publico
from generic_preview import gerar_previa_de_payload
from platform_payload_adapters import adaptar_payload

CASOS = [
    ("RapidFood", "https://rapidfood.com.br/panelamineira"),
    ("Atlas Automacao", "https://atlasautomacao.app.br/confeitariaandressamarquespds"),
    ("MenuDino", "https://pollolokoouroverde.menudino.com/"),
    ("Ola Click", "https://tatys-burger-2.ola.click/products"),
    ("Saipos", "https://temperodaleia.saipos.com/"),
    ("Loja.Menu", "https://loja.menu/bombuque"),
]

PALAVRAS_CARDAPIO = (
    "produto", "product", "item", "menu", "cardap", "categoria", "category",
    "preco", "price", "complement", "adicion", "option", "personaliz", "sabor",
)


def _schema(value: Any, depth: int = 0, max_depth: int = 6):
    if depth >= max_depth:
        if isinstance(value, dict):
            return {"tipo": "dict", "chaves": list(value.keys())[:40]}
        if isinstance(value, list):
            primeiro = value[0] if value else None
            return {"tipo": "list", "tamanho": len(value), "primeiro_chaves": list(primeiro.keys())[:40] if isinstance(primeiro, dict) else []}
        return {"tipo": type(value).__name__}
    if isinstance(value, dict):
        out = {"tipo": "dict", "chaves": list(value.keys())[:40], "filhos": {}}
        for k, v in list(value.items())[:35]:
            if isinstance(v, (dict, list)):
                out["filhos"][str(k)] = _schema(v, depth + 1, max_depth)
        return out
    if isinstance(value, list):
        primeiro = value[0] if value else None
        out = {"tipo": "list", "tamanho": len(value), "primeiro_tipo": type(primeiro).__name__ if primeiro is not None else None}
        if primeiro is not None:
            out["primeiro"] = _schema(primeiro, depth + 1, max_depth)
        return out
    return {"tipo": type(value).__name__}


def _listar_listas_de_dict(value: Any, path: str = "$", out: List[Dict[str, Any]] | None = None, depth: int = 0):
    if out is None:
        out = []
    if depth > 10 or len(out) >= 140:
        return out
    if isinstance(value, dict):
        for k, v in list(value.items())[:140]:
            _listar_listas_de_dict(v, f"{path}.{k}", out, depth + 1)
    elif isinstance(value, list):
        dicts = [x for x in value[:40] if isinstance(x, dict)]
        if dicts:
            chaves = []
            for obj in dicts[:10]:
                for k in obj.keys():
                    if k not in chaves:
                        chaves.append(k)
            out.append({"path": path, "tamanho": len(value), "chaves_amostra": chaves[:80]})
            for i, obj in enumerate(dicts[:5]):
                _listar_listas_de_dict(obj, f"{path}[{i}]", out, depth + 1)
    return out


def _score_generico(payload: Any):
    try:
        previa = gerar_previa_de_payload(payload)
        return {
            "produtos_genericos": len(previa.produtos),
            "opcoes_genericas": len(previa.grupos),
            "confianca_generica": previa.confianca,
            "candidatos_genericos": previa.total_candidatos,
        }
    except Exception as exc:
        return {"erro_previa_generica": str(exc)}


def _resumo_firestore(payload: Any):
    if not isinstance(payload, list):
        return None
    docs = []
    for row in payload[:30]:
        if not isinstance(row, dict) or not isinstance(row.get("document"), dict):
            continue
        d = row["document"]
        fields = d.get("fields") if isinstance(d.get("fields"), dict) else {}
        docs.append({"document_name": d.get("name"), "field_keys": list(fields.keys())[:140]})
    return docs or None


def _caminhos_por_nome(payload: Any, path: str = "$", out: List[Dict[str, Any]] | None = None, depth: int = 0):
    """Encontra chaves cujo nome sugere cardapio, mesmo sem combinacao suficiente."""
    if out is None:
        out = []
    if depth > 11 or len(out) >= 180:
        return out
    if isinstance(payload, dict):
        for k, v in list(payload.items())[:180]:
            kl = str(k).lower()
            if any(p in kl for p in PALAVRAS_CARDAPIO):
                resumo = {"path": f"{path}.{k}", "chave": str(k), "tipo": type(v).__name__}
                if isinstance(v, list):
                    resumo["tamanho"] = len(v)
                    if v and isinstance(v[0], dict):
                        resumo["primeiro_chaves"] = list(v[0].keys())[:80]
                elif isinstance(v, dict):
                    resumo["chaves"] = list(v.keys())[:80]
                out.append(resumo)
            if isinstance(v, (dict, list)):
                _caminhos_por_nome(v, f"{path}.{k}", out, depth + 1)
    elif isinstance(payload, list):
        for i, v in enumerate(payload[:30]):
            if isinstance(v, (dict, list)):
                _caminhos_por_nome(v, f"{path}[{i}]", out, depth + 1)
    return out


def _sinais_cardapio(payload: Any, path: str = "$", out: List[Dict[str, Any]] | None = None, depth: int = 0):
    if out is None:
        out = []
    if depth > 10 or len(out) >= 140:
        return out
    if isinstance(payload, dict):
        chaves = {str(k).lower() for k in payload.keys()}
        sinais = sorted(chaves.intersection({
            "product", "products", "produto", "produtos", "item", "items",
            "menu", "menus", "category", "categories", "categoria", "categorias",
            "price", "prices", "preco", "precos", "name", "nome", "title", "titulo",
            "options", "option_groups", "extras", "addons", "complements", "complementos",
        }))
        if len(sinais) >= 2:
            out.append({"path": path, "sinais": sinais[:30], "chaves": list(payload.keys())[:100]})
        for k, v in list(payload.items())[:140]:
            if isinstance(v, (dict, list)):
                _sinais_cardapio(v, f"{path}.{k}", out, depth + 1)
    elif isinstance(payload, list):
        for i, v in enumerate(payload[:30]):
            if isinstance(v, (dict, list)):
                _sinais_cardapio(v, f"{path}[{i}]", out, depth + 1)
    return out


def main():
    saida = []
    for nome, url in CASOS:
        print(f"[probe profundo] {nome}", flush=True)
        probe = coletar_json_publico(url, timeout_ms=40000, max_payloads=300)
        respostas = []
        for fonte, payload in probe.payloads:
            low = fonte.lower()
            if any(x in low for x in ("sentry", "fontmanifest", "assetmanifest", "analytics", "stylizations", "social_logins")):
                continue

            adaptado, adaptador = adaptar_payload(fonte, payload)
            extra = {}
            f = _resumo_firestore(payload)
            if f:
                extra["firestore"] = f
            sinais = _sinais_cardapio(payload)
            if sinais:
                extra["sinais_cardapio"] = sinais[:100]
            caminhos = _caminhos_por_nome(payload)
            if caminhos:
                extra["caminhos_cardapio"] = caminhos[:140]

            bloco_adaptado = None
            if adaptado is not payload:
                bloco_adaptado = {
                    "adaptador": adaptador,
                    "schema": _schema(adaptado),
                    "listas_de_objetos": _listar_listas_de_dict(adaptado),
                    "sinais_cardapio": _sinais_cardapio(adaptado)[:100],
                    "caminhos_cardapio": _caminhos_por_nome(adaptado)[:140],
                    **_score_generico(adaptado),
                }

            respostas.append({
                "fonte": fonte,
                "schema": _schema(payload),
                "listas_de_objetos": _listar_listas_de_dict(payload),
                **extra,
                **_score_generico(payload),
                "adaptado": bloco_adaptado,
            })
        saida.append({
            "caso": nome,
            "url": url,
            "url_final": probe.url_final,
            "erro": probe.erro,
            "total_payloads": len(probe.payloads),
            "respostas": respostas[:160],
        })
    Path("artifacts").mkdir(exist_ok=True)
    Path("artifacts/probe_endpoints.json").write_text(json.dumps(saida, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
