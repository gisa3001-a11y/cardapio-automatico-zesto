"""Diagnostico temporario de endpoints JSON para casos ainda sem produtos na V2.

Nao armazena dados completos do cardapio: registra apenas URL da resposta e
chaves de primeiro nivel para orientar novos adaptadores.
"""
import json
from pathlib import Path

from browser_probe import coletar_json_publico

CASOS = [
    ("Atlas Automacao", "https://atlasautomacao.app.br/confeitariaandressamarquespds"),
    ("Hubt", "https://www.hubt.com.br/oriental-suzano/"),
    ("MenuDino", "https://pollolokoouroverde.menudino.com/"),
    ("Neemo", "https://loja.neemo.com.br/braseiro-choperia-e-espetaria"),
    ("Ola Click", "https://tatys-burger-2.ola.click/products"),
    ("Saipos", "https://temperodaleia.saipos.com/"),
    ("Loja.Menu", "https://loja.menu/bombuque"),
]


def _shape(data):
    if isinstance(data, dict):
        return {"tipo": "dict", "chaves": list(data.keys())[:30]}
    if isinstance(data, list):
        primeiro = data[0] if data else None
        return {
            "tipo": "list",
            "tamanho": len(data),
            "primeiro_tipo": type(primeiro).__name__ if primeiro is not None else None,
            "primeiro_chaves": list(primeiro.keys())[:30] if isinstance(primeiro, dict) else [],
        }
    return {"tipo": type(data).__name__}


def main():
    saida = []
    for nome, url in CASOS:
        print(f"[probe] {nome}", flush=True)
        probe = coletar_json_publico(url, timeout_ms=30000, max_payloads=120)
        saida.append({
            "caso": nome,
            "url": url,
            "url_final": probe.url_final,
            "erro": probe.erro,
            "respostas": [
                {"fonte": fonte, **_shape(payload)}
                for fonte, payload in probe.payloads
            ],
        })
    Path("artifacts").mkdir(exist_ok=True)
    Path("artifacts/probe_endpoints.json").write_text(
        json.dumps(saida, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
