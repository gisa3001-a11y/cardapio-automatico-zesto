"""Gate de prontidao do Leitor Universal V2.

Le o relatorio real e o mapa de rede para separar duas coisas diferentes:
- falha confirmada do leitor em uma pagina que realmente expoe catalogo;
- URL/plataforma sem catalogo testavel no ambiente daquela bateria.

Os percentuais brutos continuam usando TODOS os casos. A classificacao serve apenas
para evitar que 404, Cloudflare ou pagina sem qualquer evidencia de catalogo sejam
rotulados como defeito do parser. Mesmo quando pronta, esta rotina nunca faz merge.
"""
import json
from pathlib import Path

MIN_COBERTURA = 0.80
MIN_APROVACAO = 0.70


def _ler_json(path: Path, default):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


def _network_por_caso(network_map):
    if not isinstance(network_map, list):
        return {}
    return {str(x.get("caso") or ""): x for x in network_map if isinstance(x, dict)}


def classificar_caso_sem_produtos(resultado, network=None):
    """Classifica um zero sem inventar sucesso.

    Retorna ``(classe, motivo, bloqueia_merge)``.
    ``bloqueia_merge`` somente e True quando existe evidencia de catalogo acessivel
    que o leitor deveria ter conseguido interpretar.
    """
    network = network or {}
    caso = str(resultado.get("caso") or "")
    plataforma = str(resultado.get("plataforma_detectada") or caso)
    avisos = " ".join(str(x) for x in (resultado.get("avisos") or []))
    dom = network.get("dom") or {}
    requests = network.get("requests") or []

    docs = [r for r in requests if r.get("resource_type") == "document"]
    doc_status = docs[0].get("status") if docs else None
    titulo = str(dom.get("title") or "")
    money = int(dom.get("money_mentions") or 0)
    product_words = int(dom.get("product_word_mentions") or 0)
    total_requests = len(requests)

    if doc_status == 404 or "404 Client Error" in avisos or "Error 404" in titulo:
        return (
            "url-indisponivel",
            f"{plataforma}: a URL testada respondeu 404; nao ha catalogo valido para avaliar o parser.",
            False,
        )

    if doc_status == 403 and "cloudflare" in titulo.casefold():
        return (
            "bloqueado-pelo-ambiente",
            f"{plataforma}: o documento foi bloqueado pelo Cloudflare (403) no ambiente de teste.",
            False,
        )

    # Pagina abre, mas nao ha qualquer evidencia de cardapio: sem precos, sem cards
    # e sem chamadas de dados. Isso e diferente de um parser falhar diante de dados.
    if doc_status in (None, 200) and money == 0 and total_requests == 0:
        return (
            "sem-catalogo-publico-detectavel",
            f"{plataforma}: a pagina abriu, mas nao expos precos, cards ou chamadas de catalogo durante o teste.",
            False,
        )

    # Saipos e casos semelhantes podem abrir a interface, mas a API publica usada
    # pela propria pagina retornar uma colecao vazia para aquela loja/dominio.
    api_store_ok = any(
        int(r.get("status") or 0) == 200 and "/v1/stores" in str(r.get("path") or "")
        for r in requests
    )
    if api_store_ok and money <= 3 and product_words <= 1:
        return (
            "fonte-publica-sem-catalogo",
            f"{plataforma}: a fonte publica respondeu, mas a pagina nao apresentou evidencia de produtos nessa bateria.",
            False,
        )

    # Se ha precos/produtos visiveis ou trafego de catalogo e ainda assim saiu zero,
    # este sim e um defeito que deve impedir a consideracao de merge.
    if money > 0 or product_words > 1 or total_requests > 1:
        return (
            "falha-leitor-confirmada",
            f"{plataforma}: havia evidencia de catalogo acessivel, mas o leitor retornou zero produtos.",
            True,
        )

    return (
        "nao-classificado",
        f"{plataforma}: zero produtos sem evidencia suficiente para atribuir a causa.",
        True,
    )


def avaliar_readiness(report, network_map=None):
    total = int(report.get("total_casos") or 0)
    com_produtos = int(report.get("com_produtos") or 0)
    aprovados = int(report.get("aprovados_validacao") or 0)
    cobertura = (com_produtos / total) if total else 0.0
    taxa_aprovacao = (aprovados / total) if total else 0.0

    motivos = []
    if cobertura < MIN_COBERTURA:
        motivos.append(
            f"Cobertura real {cobertura:.0%} abaixo do minimo de {MIN_COBERTURA:.0%}."
        )
    if taxa_aprovacao < MIN_APROVACAO:
        motivos.append(
            f"Aprovacao tecnica {taxa_aprovacao:.0%} abaixo do minimo de {MIN_APROVACAO:.0%}."
        )

    net = _network_por_caso(network_map or [])
    indisponiveis = []
    falhas_leitor = []
    for r in report.get("resultados", []):
        if int(r.get("produtos", 0) or 0) != 0:
            continue
        classe, motivo, bloqueia = classificar_caso_sem_produtos(r, net.get(str(r.get("caso") or "")))
        item = {"caso": r.get("caso"), "classe": classe, "motivo": motivo}
        if bloqueia:
            falhas_leitor.append(item)
        else:
            indisponiveis.append(item)

    if falhas_leitor:
        motivos.append(
            "Falhas confirmadas do leitor: " + ", ".join(str(x.get("caso")) for x in falhas_leitor)
        )

    return {
        "pronto_para_considerar_merge": not motivos,
        "merge_automatico": False,
        "total_casos": total,
        "com_produtos": com_produtos,
        "aprovados_validacao": aprovados,
        "cobertura": round(cobertura, 4),
        "taxa_aprovacao": round(taxa_aprovacao, 4),
        "limites": {
            "cobertura_minima": MIN_COBERTURA,
            "aprovacao_minima": MIN_APROVACAO,
        },
        "casos_nao_testaveis_nesta_bateria": indisponiveis,
        "falhas_confirmadas_do_leitor": falhas_leitor,
        "motivos": motivos,
        "observacao": "Pronto significa apenas elegivel para revisao/etapa seguinte; merge automatico permanece desativado.",
    }


def main():
    origem = Path("artifacts/real_url_report.json")
    if not origem.exists():
        payload = {
            "pronto_para_considerar_merge": False,
            "merge_automatico": False,
            "motivos": ["Relatorio real nao foi gerado."],
        }
    else:
        report = _ler_json(origem, {})
        network_map = _ler_json(Path("artifacts/network_map.json"), [])
        payload = avaliar_readiness(report, network_map)

    Path("artifacts").mkdir(exist_ok=True)
    Path("artifacts/readiness.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
