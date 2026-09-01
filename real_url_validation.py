"""Bateria controlada de URLs reais do Leitor Universal V2.

A validacao simula o comportamento desejado do leitor universal:
1) usa o parser oficial existente quando a plataforma ja e suportada;
2) se o parser falhar/voltar vazio, tenta a previa generica HTTP/Playwright;
3) para dominios em diagnostico, usa diretamente a previa generica.

Gera relatorio JSON e Markdown. Nao gera XLSX e nao altera a main.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from universal_router import detectar_url, ler_url_universal
from preview_runner import gerar_previa_universal
from universal_validation import validar_previa

CASOS = [
    ("RapidFood", "https://rapidfood.com.br/panelamineira"),
    ("Brendi", "https://pedido.brendi.com.br/pizzaria-tortelli/"),
    ("WhatsMenu", "https://whatsmenu.com.br/restauranterecantomineiro"),
    ("InstaDelivery", "https://instadelivery.com.br/acaidorafa1"),
    ("byFood", "https://pointdogosasco.byfood.com.br"),
    ("Atlas Automacao", "https://atlasautomacao.app.br/confeitariaandressamarquespds"),
    ("Hubt", "https://www.hubt.com.br/oriental-suzano/"),
    ("MenuDino", "https://pollolokoouroverde.menudino.com/"),
    ("Neemo", "https://loja.neemo.com.br/braseiro-choperia-e-espetaria"),
    ("Ola Click", "https://eloni-bistro.ola.click/products"),
    ("Cardapio Web", "https://app.cardapioweb.com/shakepoint_westplaza"),
    ("EntregueJa", "https://vemdeburger.entregueja.com.br/home"),
    ("Saipos", "https://xisda15.saipos.com/home"),
    ("Anota AI", "https://app.anota.ai/m/xPELP5xiw"),
    ("ECTA", "https://www.ecta.com.br/PizzariaMaisvoce?w=1"),
    ("PedidoSite", "https://gordolancheshamburgueria.pedidosite.com.br/?loja=9919"),
    ("MeuComercio", "https://meucomercio.com.br/AdegaOriom"),
    ("BigD", "https://recantodochurrasco1.bigd.im"),
    ("Loja.Menu", "https://loja.menu/bombuque"),
    ("Dominio proprio", "http://www.lapizzaiola.com.br"),
]


def _dicts_resultado_oficial(resultado):
    itens = [asdict(x) for x in (resultado.itens or [])]
    pizzas_produtos = [asdict(x) for x in (resultado.pizzas or [])]
    produtos = itens + pizzas_produtos
    grupos = [asdict(x) for x in (resultado.grupos or [])]
    pizzas = [
        {
            "codigo": p.get("codigo", ""),
            "nome": p.get("nome", ""),
            "pizza": True,
            "confianca": "alta",
            "metodo_preco_pizza": int(p.get("metodo_preco_pizza", 0) or 0),
            "motivo": "Classificado pelo parser oficial existente.",
        }
        for p in pizzas_produtos
    ]
    return produtos, grupos, pizzas


def _aplicar_previa_generica(item: Dict[str, Any], url: str, motivo_fallback: str = ""):
    previa = gerar_previa_universal(url)
    data = previa.to_dict()
    produtos = data.get("produtos") or []
    grupos = data.get("grupos") or []
    pizzas = data.get("pizzas") or []
    validacao = data.get("validacao") or {}
    avisos = list(data.get("avisos") or [])
    if motivo_fallback:
        avisos.insert(0, motivo_fallback)
    item.update({
        "status": "ok" if produtos else "sem-produtos",
        "url_final": data.get("url_final"),
        "fonte": data.get("fonte"),
        "caminho_leitura": "fallback-generico",
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
        "avisos": avisos[:10],
        "erro": data.get("erro"),
    })
    return item


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

    # Plataformas ja suportadas devem preservar o parser especifico, pois ele
    # conhece peculiaridades que o detector generico ainda nao conhece.
    if det.estrategia != "diagnostico":
        try:
            resultado, _ = ler_url_universal(det.url_normalizada, usar_playwright=True)
            if resultado is not None:
                produtos, grupos, pizzas = _dicts_resultado_oficial(resultado)
                if produtos:
                    # Parser oficial e evidencia de plataforma: um cardapio pequeno
                    # com 2 itens pode ser perfeitamente legitimo. O fallback generico
                    # continua exigindo pelo menos 3 para evitar falso positivo.
                    validacao = validar_previa(produtos, grupos, pizzas, "alta", min_produtos=2).to_dict()
                    avisos_oficiais = list(getattr(resultado, "avisos", []) or [])
                    for aviso in validacao.get("avisos") or []:
                        if aviso not in avisos_oficiais:
                            avisos_oficiais.append(aviso)
                    if validacao.get("erros"):
                        avisos_oficiais.append("Validacao tecnica: " + "; ".join(validacao["erros"][:4]))
                    item.update({
                        "status": "ok",
                        "url_final": det.url_normalizada,
                        "fonte": getattr(resultado, "origem", "parser-oficial") or "parser-oficial",
                        "caminho_leitura": "parser-oficial",
                        "confianca_previa": "alta",
                        "produtos": len(produtos),
                        "produtos_com_imagem": sum(1 for p in produtos if p.get("imagem")),
                        "produtos_com_grupo": sum(1 for p in produtos if p.get("grupos")),
                        "grupos_opcoes": len(grupos),
                        "pizzas": len(pizzas),
                        "precos_zero": sum(1 for p in produtos if float(p.get("preco", 0) or 0) == 0),
                        "score_validacao": validacao.get("score", 0),
                        "validacao_aprovada": bool(validacao.get("aprovado")),
                        "elegivel_para_teste_xlsx": bool(validacao.get("aprovado")),
                        "avisos": avisos_oficiais[:10],
                        "erro": None,
                    })
                    return item
            return _aplicar_previa_generica(
                item,
                det.url_normalizada,
                "Parser oficial nao retornou produtos; acionado fallback universal.",
            )
        except Exception as exc:
            return _aplicar_previa_generica(
                item,
                det.url_normalizada,
                f"Parser oficial falhou ({type(exc).__name__}: {exc}); acionado fallback universal.",
            )

    try:
        return _aplicar_previa_generica(item, det.url_normalizada)
    except Exception as exc:
        item.update({"status": "erro-leitura", "erro": str(exc)})
        return item


def _markdown(resultados: List[Dict[str, Any]]) -> str:
    linhas = [
        "# Relatorio controlado - Leitor Universal V2",
        "",
        "Este relatorio e de diagnostico. Nenhum caso libera XLSX automaticamente.",
        "",
        "| Caso | Detectado | Caminho | Status | Fonte | Produtos | Fotos | Produtos c/ grupos | Opcoes | Pizzas | Zero | Score |",
        "|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in resultados:
        linhas.append(
            "| {caso} | {plat} | {caminho} | {status} | {fonte} | {prod} | {fotos} | {pg} | {grupos} | {pizzas} | {zero} | {score} |".format(
                caso=r.get("caso", ""), plat=r.get("plataforma_detectada") or "-",
                caminho=r.get("caminho_leitura") or "-", status=r.get("status", "-"), fonte=r.get("fonte") or "-",
                prod=r.get("produtos", 0), fotos=r.get("produtos_com_imagem", 0),
                pg=r.get("produtos_com_grupo", 0), grupos=r.get("grupos_opcoes", 0),
                pizzas=r.get("pizzas", 0), zero=r.get("precos_zero", 0), score=r.get("score_validacao", 0),
            )
        )
    linhas += ["", "## Detalhes e falhas", ""]
    for r in resultados:
        linhas.append(f"### {r.get('caso')} — {r.get('status', '-')}")
        linhas.append(f"URL: {r.get('url')}")
        linhas.append(f"Caminho: {r.get('caminho_leitura', '-')}")
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
        "via_parser_oficial": sum(1 for r in resultados if r.get("caminho_leitura") == "parser-oficial"),
        "via_fallback_generico": sum(1 for r in resultados if r.get("caminho_leitura") == "fallback-generico" and r.get("produtos", 0) > 0),
        "aprovados_validacao": sum(1 for r in resultados if r.get("validacao_aprovada")),
        "resultados": resultados,
    }
    Path("artifacts").mkdir(exist_ok=True)
    Path("artifacts/real_url_report.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    Path("artifacts/real_url_report.md").write_text(_markdown(resultados), encoding="utf-8")
    resumo = {k: payload[k] for k in ("total_casos", "com_produtos", "via_parser_oficial", "via_fallback_generico", "aprovados_validacao")}
    print(json.dumps(resumo, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
