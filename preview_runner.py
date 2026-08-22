"""Executa a previa generica do Leitor Universal V2.

Fluxo: tenta JSON publico por HTTP; para excecoes conhecidas pode usar um probe
especializado e, se ainda necessario, Playwright generico. Payloads conhecidos
passam por adaptadores estruturais antes da normalizacao. Depois resolve preco
zero, aplica pizza e valida. Nao gera XLSX automaticamente.
"""
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import requests
from bs4 import BeautifulSoup

from generic_preview import gerar_previa_de_payload
from pizza_rules import aplicar_regras_pizza
from price_resolution import aplicar_resolucao_precos
from platform_payload_adapters import adaptar_payload
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


def _avaliar_opcoes(opcoes):
    melhor = None
    melhor_fonte = ""
    for fonte, payload in opcoes:
        try:
            payload_avaliado, adaptador = adaptar_payload(fonte, payload)
            previa = gerar_previa_de_payload(payload_avaliado)
        except Exception:
            continue
        chave = (len(previa.produtos), len(previa.grupos), previa.total_candidatos)
        if melhor is None or chave > melhor[0]:
            melhor = (chave, previa)
            melhor_fonte = f"{fonte} [{adaptador}]" if adaptador else fonte
    return melhor, melhor_fonte


def _probe_especializado(url: str, timeout: int):
    try:
        from platform_specialized_probe import probe_especializado
        opcoes = probe_especializado(url, timeout_ms=max(12000, timeout * 1000))
        melhor, fonte = _avaliar_opcoes(opcoes)
        return melhor, fonte, ""
    except Exception as exc:
        return None, "", "Probe especializado falhou: " + str(exc)


def _probe_browser(url: str, timeout: int):
    try:
        from browser_probe import coletar_json_publico
        probe = coletar_json_publico(url, timeout_ms=max(10000, timeout * 1000))
        melhor_browser, fonte_browser = _avaliar_opcoes(probe.payloads)
        aviso = ""
        if probe.erro:
            aviso = "Fallback de navegador indisponivel/incompleto: " + probe.erro
        return probe, melhor_browser, fonte_browser, aviso
    except Exception as exc:
        return None, None, "", "Fallback de navegador falhou: " + str(exc)


def gerar_previa_universal(url: str, timeout: int = 25, permitir_browser: bool = True) -> ResultadoPreviaUniversal:
    status = None
    url_final = url
    melhor = None
    melhor_fonte = ""
    browser_aviso = ""
    especial_aviso = ""
    http_aviso = ""

    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
        status = r.status_code
        url_final = r.url
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
        melhor, melhor_fonte = _avaliar_opcoes(opcoes)
    except Exception as exc:
        http_aviso = f"Leitura HTTP falhou ({type(exc).__name__}: {exc}); tentando navegador."

    if (melhor is None or len(melhor[1].produtos) == 0) and permitir_browser:
        melhor_especial, fonte_especial, especial_aviso = _probe_especializado(url_final or url, timeout)
        if melhor_especial is not None and (melhor is None or melhor_especial[0] > melhor[0]):
            melhor = melhor_especial
            melhor_fonte = fonte_especial

    if (melhor is None or len(melhor[1].produtos) == 0) and permitir_browser:
        probe, melhor_browser, fonte_browser, browser_aviso = _probe_browser(url_final or url, timeout)
        if probe is not None and probe.url_final:
            url_final = probe.url_final
        if melhor_browser is not None and (melhor is None or melhor_browser[0] > melhor[0]):
            melhor = melhor_browser
            melhor_fonte = fonte_browser

    if melhor is None or len(melhor[1].produtos) == 0:
        aviso = "Nenhuma estrutura de produtos utilizavel foi localizada por HTTP"
        if permitir_browser:
            aviso += " nem pelos fallbacks especializados/genericos de navegador"
        aviso += "."
        extras = [x for x in (http_aviso, especial_aviso, browser_aviso) if x]
        if extras:
            aviso += " " + " ".join(extras)
        return _vazio(url_final, status, melhor_fonte or ("erro" if http_aviso else "nenhuma"), aviso)

    previa = melhor[1]
    data = previa.to_dict()
    produtos_precificados, diagnosticos_precos = aplicar_resolucao_precos(data["produtos"], data["grupos"])
    produtos, diagnosticos_pizza = aplicar_regras_pizza(produtos_precificados, data["grupos"])
    pizzas = [d for d in diagnosticos_pizza if d.get("pizza")]

    avisos = list(data["avisos"])
    if http_aviso:
        avisos.append(http_aviso)
    if melhor_fonte.startswith("specialized:"):
        avisos.append("Cardapio localizado por probe especializado conservador da plataforma.")
    elif melhor_fonte.startswith("browser:"):
        avisos.append("Cardapio localizado por resposta JSON observada no navegador (SPA/dinamico).")
    if "[adaptador-" in melhor_fonte:
        avisos.append("Payload convertido por adaptador estrutural especifico antes da validacao universal.")
    if especial_aviso:
        avisos.append(especial_aviso)
    if browser_aviso:
        avisos.append(browser_aviso)

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
        url_final=url_final,
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
