"""Gate de prontidao do Leitor Universal V2.

Le o relatorio real e decide se a V2 esta tecnicamente pronta para ser considerada
para merge. Mesmo quando pronta, nao faz merge automaticamente.
"""
import json
from pathlib import Path

MIN_COBERTURA = 0.80
MIN_APROVACAO = 0.70


def main():
    origem = Path("artifacts/real_url_report.json")
    if not origem.exists():
        payload = {
            "pronto_para_considerar_merge": False,
            "motivos": ["Relatorio real nao foi gerado."],
        }
    else:
        report = json.loads(origem.read_text(encoding="utf-8"))
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

        falhas = [
            r.get("caso")
            for r in report.get("resultados", [])
            if int(r.get("produtos", 0) or 0) == 0
        ]
        if falhas:
            motivos.append("Casos sem produtos: " + ", ".join(falhas))

        payload = {
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
            "motivos": motivos,
        }

    Path("artifacts").mkdir(exist_ok=True)
    Path("artifacts/readiness.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
