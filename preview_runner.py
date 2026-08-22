"""Executa a previa generica do Leitor Universal V2.

Usa somente JSON publico encontrado na resposta HTTP/HTML. Nao gera XLSX.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import requests
from bs4 import BeautifulSoup

from generic_preview import gerar_previa_de_payload
from pizza_rules import aplicar_regras_pizza
from structure_detector import HEADERS, _extrair_json_scripts


@dataclass
class ResultadoPreviaUniversal:
    url_final: str
    status_http: Optional[int]
    fonte: str
    confianca: str
    produtos: List[Dict[str, Any]]
    grupos: List[Dict[str, Any]]
    pizzas: List[Dict[str, Any]]
    total_candidatos: int
    avisos: List[str]
    erro: Optional[str] = None

    def to_dict(self):
        return {
            "url_final": self.url_final,
            "status_http": self.status_http,
            "fonte": self.fonte,
            "confianca": self.confianca,
            "produtos": self.produtos,
            "grupos": self.grupos,
            "pizzas": self.pizzas,
            "total_candidatos": self.total_candidatos,
            "avisos": self.avisos,
            "erro": self.erro,
            "pode_gerar_xlsx": False,
        }


def gerar_previa_universal(url: str, timeout: int = 25) -> ResultadoPreviaUniversal:
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
        status = r.status_code
        r.raise_for_status()
        content_type = (r.headers.get("content-type") or "").lower()

        opcoes = []
        if "json" in content_type:
            try:
                opcoes.append(("json-direto", r.json()))
            except Exception:
                pass
        else:
            soup = BeautifulSoup(r.text, "html.parser")
            opcoes.extend(_extrair_json_scripts(soup))

        melhor = None
        melhor_fonte = ""
        for fonte, payload in opcoes:
            previa = gerar_previa_de_payload(payload)
            chave = (len(previa.produtos), len(previa.grupos), previa.total_candidatos)
            if melhor is None or chave > melhor[0]:
                melhor = (chave, previa)
                melhor_fonte = fonte

        if melhor is None:
            return ResultadoPreviaUniversal(
                url_final=r.url,
                status_http=status,
                fonte="nenhuma",
                confianca="baixa",
                produtos=[],
                grupos=[],
                pizzas=[],
                total_candidatos=0,
                avisos=["Nenhuma estrutura JSON publica utilizavel foi localizada."],
            )

        previa = melhor[1]
        data = previa.to_dict()
        produtos, diagnosticos_pizza = aplicar_regras_pizza(data["produtos"], data["grupos"])
        pizzas = [d for d in diagnosticos_pizza if d.get("pizza")]

        avisos = list(data["avisos"])
        if pizzas:
            indefinidas = sum(1 for p in pizzas if int(p.get("metodo_preco_pizza", 0) or 0) == 0)
            avisos.append(f"{len(pizzas)} possivel(is) pizza(s) identificada(s); validar regra de preco por sabor.")
            if indefinidas:
                avisos.append(f"{indefinidas} pizza(s) ficaram com metodo de preco indefinido por falta de evidencia suficiente.")

        return ResultadoPreviaUniversal(
            url_final=r.url,
            status_http=status,
            fonte=melhor_fonte,
            confianca=previa.confianca,
            produtos=produtos,
            grupos=data["grupos"],
            pizzas=pizzas,
            total_candidatos=previa.total_candidatos,
            avisos=avisos,
        )

    except Exception as exc:
        return ResultadoPreviaUniversal(
            url_final=url,
            status_http=None,
            fonte="erro",
            confianca="baixa",
            produtos=[],
            grupos=[],
            pizzas=[],
            total_candidatos=0,
            avisos=[],
            erro=str(exc),
        )
