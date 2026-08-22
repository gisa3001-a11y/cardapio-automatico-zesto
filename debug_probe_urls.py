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
    ("Hubt", "https://www.hubt.com.br/oriental-suzano/"),
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
    if out is None: out = []
    if depth > 8 or len(out) >= 80: return out
    if isinstance(value, dict):
        for k, v in list(value.items())[:80]: _listar_listas_de_dict(v, f"{path}.{k}", out, depth + 1)
    elif isinstance(value, list):
        dicts = [x for x in value[:20] if isinstance(x, dict)]
        if dicts:
            chaves = []
            for obj in dicts[:5]:
                for k in obj.keys():
                    if k not in chaves: chaves.append(k)
            out.append({"path": path, "tamanho": len(value), "chaves_amostra": chaves[:50]})
            for i, obj in enumerate(dicts[:3]): _listar_listas_de_dict(obj, f"{path}[{i}]", out, depth + 1)
    return out


def _score_generico(payload: Any):
    try:
        previa = gerar_previa_de_payload(payload)
        return {"produtos_genericos": len(previa.produtos), "opcoes_genericas": len(previa.grupos), "confianca_generica": previa.confianca, "candidatos_genericos": previa.total_candidatos}
    except Exception as exc:
        return {"erro_previa_generica": str(exc)}


def _resumo_hubt(payload: Any):
    if not isinstance(payload, dict) or not isinstance(payload.get("modules"), list): return None
    tipos = {str(x.get("id")): x.get("name") for x in (payload.get("moduleTypes") or []) if isinstance(x, dict)}
    mods = []
    for m in payload.get("modules") or []:
        if not isinstance(m, dict): continue
        itens = m.get("items") or []
        amostra = itens[0] if itens and isinstance(itens[0], dict) else {}
        props = m.get("properties") if isinstance(m.get("properties"), dict) else {}
        mt = str(m.get("_moduleType") or "")
        mods.append({
            "module_id": m.get("_module"), "module_type_id": mt, "module_type_name": tipos.get(mt),
            "itens": len(itens) if isinstance(itens, list) else 0,
            "item_chaves": list(amostra.keys())[:60], "properties_chaves": list(props.keys())[:60],
        })
    return {"modules": mods, "module_types": tipos}


def _resumo_firestore(payload: Any):
    if not isinstance(payload, list): return None
    docs = []
    for row in payload[:20]:
        if not isinstance(row, dict) or not isinstance(row.get("document"), dict): continue
        d = row["document"]
        fields = d.get("fields") if isinstance(d.get("fields"), dict) else {}
        docs.append({"document_name": d.get("name"), "field_keys": list(fields.keys())[:80]})
    return docs or None


def main():
    saida = []
    for nome, url in CASOS:
        print(f"[probe profundo] {nome}", flush=True)
        probe = coletar_json_publico(url, timeout_ms=35000, max_payloads=220)
        respostas = []
        for fonte, payload in probe.payloads:
            low = fonte.lower()
            if any(x in low for x in ("sentry", "fontmanifest", "assetmanifest", "analytics", "stylizations", "social_logins")): continue
            extra = {}
            h = _resumo_hubt(payload)
            if h: extra["hubt"] = h
            f = _resumo_firestore(payload)
            if f: extra["firestore"] = f
            respostas.append({"fonte": fonte, "schema": _schema(payload), "listas_de_objetos": _listar_listas_de_dict(payload), **extra, **_score_generico(payload)})
        saida.append({"caso": nome, "url": url, "url_final": probe.url_final, "erro": probe.erro, "respostas": respostas[:100]})
    Path("artifacts").mkdir(exist_ok=True)
    Path("artifacts/probe_endpoints.json").write_text(json.dumps(saida, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0

if __name__ == "__main__": raise SystemExit(main())
