"""Bateria controlada de URLs reais do Leitor Universal V2.

Gera relatorio JSON e Markdown. Nao gera XLSX e nao altera a main.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from universal_router import detectar_url
from preview_runner import gerar_previa_universal

CASOS = [
    ("RapidFood", "https://rapidfood.com.br/panelamineira"),
    ("Brendi", "https://pedido.brendi.com.br/flores-pizzas-artesanais-colina-azul"),
    ("WhatsMenu", "https://whatsmenu.com.br/restauranterecantomineiro"),
    ("InstaDelivery", "https://instadelivery.com.br/acaidorafa1"),
    ("byFood", "https://pointdogosasco.byfood.com.br"),
    ("Atlas Automacao", "https://atlasautomacao.app.br/confeitariaandressamarquespds"),
    ("Hubt", "https://www.hubt.com.br/oriental-suzano/"),
    ("MenuDino", "https://pollolokoouroverde.menudino.com/"),
    ("Neemo", "https://loja.neemo.com.br/braseiro-choperia-e-espetaria"),
    ("Ola Click", "https://tatys-burger-2.ola.click/products"),
    ("Cardapio Web", "https://app.cardapioweb.com/shakepoint_westplaza"),
    ("EntregueJa", "https://vemdeburger.entregueja.com.br/home"),
    ("Saipos", "https://temperodaleia.saipos.com/"),
    ("Anota AI", "https://app.anota.ai/m/xPELP5xiw"),
    ("ECTA", "https://www.ecta.com.br/PizzariaMaisvoce?w=1"),
    ("PedidoSite", "https://gordolancheshamburgueria.pedidosite.com.br/?loja=9919"),
    ("MeuComercio", "https://meucomercio.com.br/AdegaOriom"),
    ("BigD", "https://recantodochurrasco1.bigd.im"),
    ("Loja.Menu", "https://loja.menu/bombuque"),
    ("Dominio proprio", "http://www.lapizzaiola.com.br"),
]


def _resumir(label: str, url: str) -> Dict[str, Any]:
    item: Dict[str, Any] = {"caso": label, "url": url}
    try:
        det = detectar_url(url)
        item.update({
            "plataforma_detectada": det.plataforma,
            "url_normalizada": det.url_normalizada,
            "estrategia": det.estrategia,
            "confianca_deteccao": det.confianca,
        })
    except Exception as exc:
        item.update({"status": "erro-roteamento", "erro": str(exc)})
        return item

    try:
        previa = gerar_previa_universal(det.url_normalizada)
        data = previa.to_dict()
        produtos = data.get("produtos") or []
        grupos = data.get("grupos") or []
        pizzas = data.get("pizzas") or []
        validacao = data.get("validacao") or {}
        item.update({
            "status": "ok" if produtos else "sem-produtos",
            "url_final": data.get("url_final"),
            "fonte": data.get("fonte"),
            "confianca_previa": data.get("confianca"),
            "produtos": len(produtos),
            "produtos_com_imagem": sum(1 for p in produtos if p.get("imagem")),
            "produtos_com_grupo": sum(1 for p in produtos if p.get("grupos")),
            "grupos_opcoes": len(grupos),
            "pizzas": len(pizzas),
            "precos_zero": sum(1 for p in produtos if float(p.get("preco", 0) or 0) == 0),
            "score_validacao": validacao.get("score", 0),
            "validacao_aprovada": bool(validacao.get("aprovado")),
            "elegivel_para_teste_xlsx": bool(data.get("elegivel_para_teste_xlsx")),
            "avisos": (data.get("avisos") or [])[:8],
            "erro": data.get("erro"),
        })
    except Exception as exc:
        item.update({"status": "erro-leitura", "erro": str(exc)})
    return item


def _markdown(resultados: List[Dict[str, Any]]) -> str:
    linhas = [
        "# Relatorio controlado - Leitor Universal V2",
        "",
        "Este relatorio e de diagnostico. Nenhum caso libera XLSX automaticamente.",
        "",
        "| Caso | Detectado | Status | Fonte | Produtos | Fotos | Produtos c/ grupos | Opcoes | Pizzas | Zero | Score |",
        "|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in resultados:
        linhas.append(
            "| {caso} | {plat} | {status} | {fonte} | {prod} | {fotos} | {pg} | {grupos} | {pizzas} | {zero} | {score} |".format(
                caso=r.get("caso", ""), plat=r.get("plataforma_detectada") or "-",
                status=r.get("status", "-"), fonte=r.get("fonte") or "-",
                prod=r.get("produtos", 0), fotos=r.get("produtos_com_imagem", 0),
                pg=r.get("produtos_com_grupo", 0), grupos=r.get("grupos_opcoes", 0),
                pizzas=r.get("pizzas", 0), zero=r.get("precos_zero", 0), score=r.get("score_validacao", 0),
            )
        )
    linhas += ["", "## Detalhes e falhas", ""]
    for r in resultados:
        linhas.append(f"### {r.get('caso')} — {r.get('status', '-')}")
        linhas.append(f"URL: {r.get('url')}")
        if r.get("erro"):
            linhas.append(f"Erro: {r.get('erro')}")
        for aviso in r.get("avisos") or []:
            linhas.append(f"- {aviso}")
        linhas.append("")
    return "\n".join(linhas)


def main() -> int:
    resultados = []
    for label, url in CASOS:
        print(f"[V2] {label}: {url}", flush=True)
        resultados.append(_resumir(label, url))

    payload = {
        "gerado_em_utc": datetime.now(timezone.utc).isoformat(),
        "total_casos": len(resultados),
        "com_produtos": sum(1 for r in resultados if r.get("produtos", 0) > 0),
        "aprovados_validacao": sum(1 for r in resultados if r.get("validacao_aprovada")),
        "resultados": resultados,
    }
    Path("artifacts").mkdir(exist_ok=True)
    Path("artifacts/real_url_report.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    Path("artifacts/real_url_report.md").write_text(_markdown(resultados), encoding="utf-8")
    print(json.dumps({k: payload[k] for k in ("total_casos", "com_produtos", "aprovados_validacao")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
