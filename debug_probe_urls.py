"""Diagnostico temporario de endpoints JSON para casos ainda sem produtos na V2.

Nao armazena o cardapio completo. Registra apenas estrutura, caminhos de listas,
chaves de amostras e resumos especificos para orientar adaptadores.
"""
import json
from pathlib import Path
from typing import Any, Dict, List

from browser_probe import coletar_json_publico
from generic_preview import gerar_previa_de_payload

CASOS = [
    ("RapidFood", "https://rapidfood.com.br/panelamineira"),
    ("Atlas Automacao", "https://atlasautomacao.app.br/confeitariaandressamarquespds"),
    ("MenuDino", "https://pollolokoouroverde.menudino.com/"),
    ("Ola Click", "https://tatys-burger-2.ola.click/products"),
    ("Saipos", "https://temperodaleia.saipos.com/"),
    ("Loja.Menu", "https://loja.menu/bombuque"),
]


def _schema(value: Any, depth: int = 0, max_depth: int = 5):
    if depth >= max_depth:
        if isinstance(value, dict):
            return {"tipo": "dict", "chaves": list(value.keys())[:30]}
        if isinstance(value, list):
            primeiro = value[0] if value else None
            return {"tipo": "list", "tamanho": len(value), "primeiro_chaves": list(primeiro.keys())[:30] if isinstance(primeiro, dict) else []}
        return {"tipo": type(value).__name__}
    if isinstance(value, dict):
        out = {"tipo": "dict", "chaves": list(value.keys())[:30], "filhos": {}}
        for k, v in list(value.items())[:25]:
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
    if depth > 8 or len(out) >= 100:
        return out
    if isinstance(value, dict):
        for k, v in list(value.items())[:100]:
            _listar_listas_de_dict(v, f"{path}.{k}", out, depth + 1)
    elif isinstance(value, list):
        dicts = [x for x in value[:30] if isinstance(x, dict)]
        if dicts:
            chaves = []
            for obj in dicts[:8]:
                for k in obj.keys():
                    if k not in chaves:
                        chaves.append(k)
            out.append({"path": path, "tamanho": len(value), "chaves_amostra": chaves[:60]})
            for i, obj in enumerate(dicts[:4]):
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
        docs.append({"document_name": d.get("name"), "field_keys": list(fields.keys())[:100]})
    return docs or None


def _sinais_cardapio(payload: Any, path: str = "$", out: List[Dict[str, Any]] | None = None, depth: int = 0):
    """Localiza objetos com chaves semanticamente proximas de produto/cardapio."""
    if out is None:
        out = []
    if depth > 9 or len(out) >= 120:
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
            out.append({"path": path, "sinais": sinais[:30], "chaves": list(payload.keys())[:80]})
        for k, v in list(payload.items())[:120]:
            if isinstance(v, (dict, list)):
                _sinais_cardapio(v, f"{path}.{k}", out, depth + 1)
    elif isinstance(payload, list):
        for i, v in enumerate(payload[:20]):
            if isinstance(v, (dict, list)):
                _sinais_cardapio(v, f"{path}[{i}]", out, depth + 1)
    return out


def main():
    saida = []
    for nome, url in CASOS:
        print(f"[probe profundo] {nome}", flush=True)
        probe = coletar_json_publico(url, timeout_ms=40000, max_payloads=260)
        respostas = []
        for fonte, payload in probe.payloads:
            low = fonte.lower()
            if any(x in low for x in ("sentry", "fontmanifest", "assetmanifest", "analytics", "stylizations", "social_logins")):
                continue
            extra = {}
            f = _resumo_firestore(payload)
            if f:
                extra["firestore"] = f
            sinais = _sinais_cardapio(payload)
            if sinais:
                extra["sinais_cardapio"] = sinais[:80]
            respostas.append({
                "fonte": fonte,
                "schema": _schema(payload),
                "listas_de_objetos": _listar_listas_de_dict(payload),
                **extra,
                **_score_generico(payload),
            })
        saida.append({
            "caso": nome,
            "url": url,
            "url_final": probe.url_final,
            "erro": probe.erro,
            "total_payloads": len(probe.payloads),
            "respostas": respostas[:140],
        })
    Path("artifacts").mkdir(exist_ok=True)
    Path("artifacts/probe_endpoints.json").write_text(json.dumps(saida, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
