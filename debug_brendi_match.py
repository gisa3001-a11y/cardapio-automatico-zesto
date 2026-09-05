"""Diagnóstico controlado da correspondência produto -> tamanho na Brendi real.

Não altera o parser nem materializa dados no app. Apenas registra os nomes que o
parser oficial produziu e os tamanhos resolvidos do __NUXT_DATA__ para explicar
correspondências exatas ausentes/ambíguas antes de qualquer correção de produção.
"""
from __future__ import annotations

import json
from pathlib import Path

import requests

from brendi_result_enrichment import extrair_nuxt_data_html, enriquecer_resultado_brendi_nuxt
from fetchers import buscar_por_url

URL = "https://pedido.brendi.com.br/pizzaria-tortelli/"


def main() -> int:
    resultado = buscar_por_url(URL, usar_playwright=False)
    resposta = requests.get(
        URL,
        timeout=25,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/131.0 Safari/537.36"
            )
        },
    )
    resposta.raise_for_status()
    nuxt_data = extrair_nuxt_data_html(resposta.text)
    _, auditoria = enriquecer_resultado_brendi_nuxt(resultado, nuxt_data)

    payload = {
        "url": URL,
        "origem": str(getattr(resultado, "origem", "") or ""),
        "produtos": len(list(resultado.itens or []) + list(resultado.pizzas or [])),
        "opcoes_antes_ou_depois": len(resultado.grupos or []),
        "auditoria": auditoria,
    }
    Path("artifacts").mkdir(exist_ok=True)
    Path("artifacts/brendi_match.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    resumo = {
        "produtos": payload["produtos"],
        "produtos_vinculados": auditoria.get("produtos_vinculados", 0),
        "opcoes_materializadas": auditoria.get("opcoes_materializadas", 0),
        "tamanhos": [x.get("nome") for x in auditoria.get("tamanhos_ativos", [])],
        "nomes_produtos": [x.get("nome") for x in auditoria.get("produtos_lidos", [])],
    }
    print(json.dumps(resumo, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
