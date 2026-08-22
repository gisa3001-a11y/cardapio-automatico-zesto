"""Executa a previa generica do Leitor Universal V2.

Fluxo: localiza JSON publico -> normaliza produtos/grupos -> resolve preco zero
quando ha evidencia -> aplica regras de pizza -> valida tecnicamente.
Nao gera XLSX automaticamente.
"""
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import requests
from bs4 import BeautifulSoup

from generic_preview import gerar_previa_de_payload
from pizza_rules import aplicar_regras_pizza
from price_resolution import aplicar_resolucao_precos
from structure_detector import HEADERS, _extrair_json_scripts
from universal_validation import validar_previa

@dataclass
class ResultadoPreviaUniversal:
    url_final: str
    status_http: Optional[int]
    fonte: str
    confianca: str
    produtos: List[Dict[str, Any]]
    grupos: List[Dict[str, Any]]
    pizzas: List[Dict[str, Any]]
    diagnosticos_precos: List[Dict[str, Any]]
    validacao: Dict[str, Any]
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
            "diagnosticos_precos": self.diagnosticos_precos,
            "validacao": self.validacao,
            "total_candidatos": self.total_candidatos,
            "avisos": self.avisos,
            # Mesmo se a validacao tecnica aprovar, a exportacao automatica fica
            # bloqueada ate passar pela bateria controlada de URLs reais.
            "pode_gerar_xlsx": False,
            "elegivel_para_teste_xlsx": bool(self.validacao.get("aprovado")),
        }

def _vazio(url: str, status: Optional[int], fonte: str, aviso: str = "", erro: Optional[str] = None):
    return ResultadoPreviaUniversal(
        url_final=url, status_http=status, fonte=fonte, confianca="baixa",
        produtos=[], grupos=[], pizzas=[], diagnosticos_precos=[],
        validacao={"aprovado": False, "score": 0, "erros": [aviso] if aviso else [], "avisos": [], "metricas": {}, "pode_gerar_xlsx": False},
        total_candidatos=0, avisos=[aviso] if aviso else [], erro=erro,
    )

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
            return _vazio(r.url, status, "nenhuma", "Nenhuma estrutura JSON publica utilizavel foi localizada.")

        previa = melhor[1]
        data = previa.to_dict()

        produtos_precificados, diagnosticos_precos = aplicar_resolucao_precos(data["produtos"], data["grupos"])
        produtos, diagnosticos_pizza = aplicar_regras_pizza(produtos_precificados, data["grupos"])
        pizzas = [d for d in diagnosticos_pizza if d.get("pizza")]

        avisos = list(data["avisos"])
        resolvidos = sum(1 for d in diagnosticos_precos if d.get("resolvido"))
        pendentes_zero = sum(1 for d in diagnosticos_precos if float(d.get("preco_original", 0) or 0) == 0 and not d.get("resolvido"))
        if resolvidos:
            avisos.append(f"{resolvidos} produto(s) com preco zero tiveram sugestao de preco resolvida por grupo estruturado.")
        if pendentes_zero:
            avisos.append(f"{pendentes_zero} produto(s) seguem com preco zero por falta de evidencia segura.")

        if pizzas:
            indefinidas = sum(1 for p in pizzas if int(p.get("metodo_preco_pizza", 0) or 0) == 0)
            avisos.append(f"{len(pizzas)} possivel(is) pizza(s) identificada(s); validar regra de preco por sabor.")
            if indefinidas:
                avisos.append(f"{indefinidas} pizza(s) ficaram com metodo de preco indefinido por falta de evidencia suficiente.")

        validacao = validar_previa(produtos, data["grupos"], pizzas, previa.confianca).to_dict()
        avisos.extend(x for x in validacao.get("avisos", []) if x not in avisos)
        if validacao.get("erros"):
            avisos.append("Previa ainda nao elegivel para teste de exportacao: " + "; ".join(validacao["erros"][:4]))

        return ResultadoPreviaUniversal(
            url_final=r.url,
            status_http=status,
            fonte=melhor_fonte,
            confianca=previa.confianca,
            produtos=produtos,
            grupos=data["grupos"],
            pizzas=pizzas,
            diagnosticos_precos=diagnosticos_precos,
            validacao=validacao,
            total_candidatos=previa.total_candidatos,
            avisos=avisos,
        )

    except Exception as exc:
        return _vazio(url, None, "erro", erro=str(exc))
