"""Entrada segura do Leitor Universal V2 para o app atual.

Nao altera o comportamento dos parsers oficiais. A funcao tenta primeiro o
fluxo existente; o universal so entra como fallback quando a leitura oficial
falha ou volta vazia. Para RapidFood, o Universal V2 entra primeiro porque o
HTTP direto do leitor oficial pode receber 403 no Streamlit Cloud.
O resultado universal precisa estar aprovado antes de ser convertido para os
modelos usados pelo XLSX atual.
"""
from typing import Callable, Tuple

from models import Resultado
from preview_runner import gerar_previa_universal
from universal_integration import converter_previa_para_resultado


def _tem_produtos(resultado: Resultado) -> bool:
    return bool(resultado and (resultado.itens or resultado.pizzas))


def _eh_rapidfood(url: str) -> bool:
    return "rapidfood.com.br" in (url or "").lower()


def buscar_com_fallback_universal(
    url: str,
    buscar_oficial: Callable[..., Resultado],
    usar_playwright: bool = True,
) -> Tuple[Resultado, str]:
    """Preserva o leitor atual; RapidFood prioriza o V2 para evitar o 403 HTTP."""

    # No Streamlit Cloud o RapidFood pode negar a requisicao HTTP direta com
    # 403, enquanto o probe especializado do Universal V2 consegue seguir pelo
    # Chromium renderizado. Priorizamos esse caminho apenas para esta plataforma
    # para nao alterar o comportamento das demais.
    if _eh_rapidfood(url):
        try:
            previa_rf = gerar_previa_universal(url, permitir_browser=usar_playwright)
            convertido_rf = converter_previa_para_resultado(previa_rf, exigir_aprovacao=True)
            convertido_rf.avisos.insert(
                0,
                "RapidFood lido pelo Leitor Universal V2 antes do fluxo HTTP oficial para evitar bloqueio 403 no Streamlit Cloud.",
            )
            return convertido_rf, "universal-v2"
        except Exception:
            # Se o probe especializado nao conseguir um resultado aprovado,
            # mantemos o fluxo anterior como rede de seguranca.
            pass

    erro_oficial = None
    try:
        atual = buscar_oficial(url, usar_playwright=usar_playwright)
        if _tem_produtos(atual):
            return atual, "oficial"
    except Exception as exc:
        erro_oficial = exc

    previa = gerar_previa_universal(url, permitir_browser=usar_playwright)
    convertido = converter_previa_para_resultado(previa, exigir_aprovacao=True)
    convertido.avisos.insert(0, "Leitura recuperada pelo Leitor Universal V2 após o fluxo oficial não produzir um cardápio utilizável.")
    if erro_oficial:
        convertido.avisos.append(f"Falha do leitor oficial antes do fallback universal: {type(erro_oficial).__name__}.")
    return convertido, "universal-v2"
