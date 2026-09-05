"""Entrada segura do Leitor Universal V2 para o app atual.

Preserva os parsers oficiais e usa o universal como fallback quando necessário.
RapidFood prioriza o V2 por causa do 403 observado no Streamlit Cloud. Brendi
mantém o parser oficial e recebe apenas o enriquecimento Nuxt já comprovado pela
bateria real de XLSX; se a fonte mudar, o enriquecimento falha fechado e o
resultado oficial é preservado sem inventar vínculos.
"""
from typing import Callable, Tuple

import requests

from brendi_result_enrichment import extrair_nuxt_data_html, enriquecer_resultado_brendi_nuxt
from models import Resultado
from preview_runner import gerar_previa_universal
from universal_integration import converter_previa_para_resultado


def _tem_produtos(resultado: Resultado) -> bool:
    return bool(resultado and (resultado.itens or resultado.pizzas))


def _eh_rapidfood(url: str) -> bool:
    return "rapidfood.com.br" in (url or "").lower()


def _eh_brendi(url: str) -> bool:
    return "pedido.brendi.com.br" in (url or "").lower()


def _enriquecer_brendi_url(resultado: Resultado, url: str) -> bool:
    resposta = requests.get(
        url,
        timeout=25,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/131.0 Safari/537.36"
            )
        },
    )
    resposta.raise_for_status()
    nuxt_data = extrair_nuxt_data_html(resposta.text)
    _, auditoria = enriquecer_resultado_brendi_nuxt(resultado, nuxt_data)
    return (
        int(auditoria.get("produtos_vinculados") or 0) >= 1
        and int(auditoria.get("opcoes_materializadas") or 0) >= 1
    )


def buscar_com_fallback_universal(
    url: str,
    buscar_oficial: Callable[..., Resultado],
    usar_playwright: bool = True,
) -> Tuple[Resultado, str]:
    """Preserva o leitor atual, com exceções comprovadas e isoladas por plataforma."""

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
            pass

    erro_oficial = None
    try:
        atual = buscar_oficial(url, usar_playwright=usar_playwright)
        if _tem_produtos(atual):
            if _eh_brendi(url):
                try:
                    if _enriquecer_brendi_url(atual, url):
                        atual.avisos.insert(
                            0,
                            "Pizzas Brendi enriquecidas pelo estado Nuxt público validado para preservar tamanhos, sabores, preços e vínculos.",
                        )
                        return atual, "oficial+brendi-nuxt"
                    atual.avisos.append(
                        "Brendi: o enriquecimento Nuxt não encontrou vínculos comprovados; o resultado oficial foi preservado sem associação aproximada."
                    )
                except Exception as exc:
                    atual.avisos.append(
                        f"Brendi: enriquecimento Nuxt indisponível ({type(exc).__name__}); o resultado oficial foi preservado."
                    )
            return atual, "oficial"
    except Exception as exc:
        erro_oficial = exc

    previa = gerar_previa_universal(url, permitir_browser=usar_playwright)
    convertido = converter_previa_para_resultado(previa, exigir_aprovacao=True)
    convertido.avisos.insert(0, "Leitura recuperada pelo Leitor Universal V2 após o fluxo oficial não produzir um cardápio utilizável.")
    if erro_oficial:
        convertido.avisos.append(f"Falha do leitor oficial antes do fallback universal: {type(erro_oficial).__name__}.")
    return convertido, "universal-v2"
