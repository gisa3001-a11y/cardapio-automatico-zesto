"""Executa a bateria real V2 com paralelismo controlado.

Importa a logica de real_url_validation.py; nao gera XLSX.
A quantidade de workers foi reduzida para evitar disputa de Chromium/rede entre
plataformas dinamicas. Casos que voltam sem produtos recebem uma unica segunda
tentativa antes de serem classificados como falha real.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
import json
import time

from real_url_validation import CASOS, _resumir, _markdown


def _executar_com_retry(label, url):
    primeiro = _resumir(label, url)
    if primeiro.get("produtos", 0) > 0:
        primeiro["tentativas"] = 1
        return primeiro

    # Uma repeticao curta reduz falso negativo de SPA/Chromium sem mascarar falha.
    time.sleep(1.5)
    segundo = _resumir(label, url)
    segundo["tentativas"] = 2
    segundo["primeira_tentativa_status"] = primeiro.get("status")
    segundo["primeira_tentativa_erro"] = primeiro.get("erro")
    return segundo


def main() -> int:
    resultados_por_indice = {}
    # Quatro browsers simultaneos causaram oscilacao em RapidFood/Loja.Menu.
    # Dois mantem o CI rapido, mas com memoria/rede mais estaveis.
    max_workers = 2

    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="v2-url") as pool:
        futuros = {
            pool.submit(_executar_com_retry, label, url): (idx, label, url)
            for idx, (label, url) in enumerate(CASOS)
        }
        for futuro in as_completed(futuros):
            idx, label, url = futuros[futuro]
            try:
                resultado = futuro.result()
            except Exception as exc:
                resultado = {
                    "caso": label,
                    "url": url,
                    "status": "erro-executor",
                    "erro": f"{type(exc).__name__}: {exc}",
                    "tentativas": 1,
                }
            resultados_por_indice[idx] = resultado
            print(
                f"[V2] concluido {idx + 1}/{len(CASOS)} - {label}: "
                f"{resultado.get('status')} / {resultado.get('produtos', 0)} produto(s) / "
                f"tentativas={resultado.get('tentativas', 1)}",
                flush=True,
            )

    resultados = [resultados_por_indice[i] for i in range(len(CASOS))]
    payload = {
        "gerado_em_utc": datetime.now(timezone.utc).isoformat(),
        "execucao": "paralela-controlada-com-retry",
        "workers": max_workers,
        "total_casos": len(resultados),
        "com_produtos": sum(1 for r in resultados if r.get("produtos", 0) > 0),
        "via_parser_oficial": sum(1 for r in resultados if r.get("caminho_leitura") == "parser-oficial"),
        "via_fallback_generico": sum(
            1 for r in resultados
            if r.get("caminho_leitura") == "fallback-generico" and r.get("produtos", 0) > 0
        ),
        "aprovados_validacao": sum(1 for r in resultados if r.get("validacao_aprovada")),
        "reexecutados": sum(1 for r in resultados if r.get("tentativas", 1) > 1),
        "resultados": resultados,
    }

    Path("artifacts").mkdir(exist_ok=True)
    Path("artifacts/real_url_report.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    Path("artifacts/real_url_report.md").write_text(_markdown(resultados), encoding="utf-8")
    print(json.dumps({
        "total_casos": payload["total_casos"],
        "com_produtos": payload["com_produtos"],
        "via_parser_oficial": payload["via_parser_oficial"],
        "via_fallback_generico": payload["via_fallback_generico"],
        "aprovados_validacao": payload["aprovados_validacao"],
        "reexecutados": payload["reexecutados"],
    }, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
