"""Guardas de qualidade sobre a bateria XLSX real.

Mantém o teste fail-closed quando uma fonte conhecida sofre colapso brusco de
cobertura mas ainda consegue gerar um XLSX tecnicamente válido.
"""
from __future__ import annotations

import json
from pathlib import Path


MINIMOS_COMPROVADOS = {
    # A mesma loja de controle retornou 204 produtos na validação real de URL.
    # O piso de 50 é propositalmente conservador: evita aprovar resultados
    # claramente truncados (como 1 produto) sem exigir estabilidade exata de 204.
    "Saipos": {"produtos": 50},
}


def main() -> int:
    path = Path("artifacts/real_xlsx_report.json")
    if not path.exists():
        print("quality-guard: relatório XLSX real ausente")
        return 1

    payload = json.loads(path.read_text(encoding="utf-8"))
    resultados = {r.get("caso"): r for r in payload.get("resultados", []) if isinstance(r, dict)}
    falhas = []

    for caso, campos in MINIMOS_COMPROVADOS.items():
        item = resultados.get(caso) or {}
        for campo, minimo in campos.items():
            atual = int(item.get(campo) or 0)
            if atual < minimo:
                falhas.append(f"{caso}: {campo}={atual}, mínimo conservador={minimo}")

    if falhas:
        print(json.dumps({"status": "regressao-estrutura", "falhas": falhas}, ensure_ascii=False))
        return 1

    print(json.dumps({"status": "ok", "guardas": MINIMOS_COMPROVADOS}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
