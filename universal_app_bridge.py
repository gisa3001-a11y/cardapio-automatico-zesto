"""Entrada segura do Leitor Universal V2 para o app atual.

Nao altera o comportamento dos parsers oficiais. A funcao tenta primeiro o
fluxo existente; o universal so entra como fallback quando a leitura oficial
falha ou volta vazia. O resultado universal precisa estar aprovado antes de
ser convertido para os modelos usados pelo XLSX atual.
"""
from typing import Callable, Tuple

from models import Resultado
from preview_runner import gerar_previa_universal
from universal_integration import converter_previa_para_resultado


def _tem_produtos(resultado: Resultado) -> bool:
    return bool(resultado and (resultado.itens or resultado.pizzas))


def buscar_com_fallback_universal(
    url: str,
    buscar_oficial: Callable[..., Resultado],
    usar_playwright: bool = True,
) -> Tuple[Resultado, str]:
    """Preserva o leitor atual e usa V2 somente se ele nao produzir cardapio."""
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
