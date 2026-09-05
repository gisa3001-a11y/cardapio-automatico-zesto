"""Entrada segura do Leitor Universal V2 para o app atual.

Preserva os parsers oficiais e usa o universal como fallback quando necessário.
RapidFood prioriza o V2 por causa do 403 observado no Streamlit Cloud. Brendi
mantém o parser oficial e recebe apenas o enriquecimento Nuxt já comprovado pela
bateria real de XLSX. Ola Click preserva o parser oficial e materializa somente
variantes nomeadas comprovadas pelo estado Nuxt público; variantes únicas sem nome
continuam sendo tratadas apenas como preço normal do produto.
"""
import re
from typing import Callable, Tuple

import requests

from brendi_result_enrichment import extrair_nuxt_data_html, enriquecer_resultado_brendi_nuxt
from olaclick_variant_enrichment import (
    extrair_nuxt_data_html as extrair_nuxt_data_olaclick,
    enriquecer_resultado_olaclick_variantes,
)
from models import Resultado
from preview_runner import gerar_previa_universal
from universal_integration import converter_previa_para_resultado
from utils import parece_pizza


def _tem_produtos(resultado: Resultado) -> bool:
    return bool(resultado and (resultado.itens or resultado.pizzas))


def _eh_anota(url: str) -> bool:
    u = (url or "").lower()
    return "anota.ai" in u or "anotaai" in u


def _eh_rapidfood(url: str) -> bool:
    return "rapidfood.com.br" in (url or "").lower()


def _eh_brendi(url: str) -> bool:
    return "pedido.brendi.com.br" in (url or "").lower()


def _eh_olaclick(url: str) -> bool:
    return "ola.click" in (url or "").lower()


def _sanear_vinhos_anota(resultado: Resultado) -> int:
    """Move apenas falsos positivos de vinho para itens regulares.

    A bateria real mostrou vinhos comuns dentro de ``resultado.pizzas`` sem qualquer
    evidência de pizza no próprio nome. A correção replica o critério conservador já
    documentado no validator: o item precisa conter a palavra vinho e o nome, sozinho,
    não pode indicar pizza. Nenhum outro produto é reclassificado.

    O marcador privado impede apenas que o validator desfaça esta mesma decisão
    comprovada; categoria, descrição e demais dados de origem permanecem intactos.
    """
    manter_pizzas = []
    mover_itens = []
    for produto in resultado.pizzas:
        nome = str(getattr(produto, "nome", "") or "")
        categoria = str(getattr(produto, "categoria", "") or "")
        eh_vinho = bool(re.search(r"\bvinho(?:s)?\b", f"{nome} {categoria}", re.IGNORECASE))
        if eh_vinho and not parece_pizza(nome, "", ""):
            produto.pizza = False
            produto.metodo_preco_pizza = 0
            produto._regular_saneado_universal = "anota-vinho"
            mover_itens.append(produto)
        else:
            manter_pizzas.append(produto)
    if mover_itens:
        resultado.pizzas = manter_pizzas
        resultado.itens.extend(mover_itens)
    return len(mover_itens)


def _http_html(url: str) -> str:
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
    return resposta.text


def _enriquecer_brendi_url(resultado: Resultado, url: str) -> bool:
    nuxt_data = extrair_nuxt_data_html(_http_html(url))
    _, auditoria = enriquecer_resultado_brendi_nuxt(resultado, nuxt_data)
    return (
        int(auditoria.get("produtos_vinculados") or 0) >= 1
        and int(auditoria.get("opcoes_materializadas") or 0) >= 1
    )


def _enriquecer_olaclick_url(resultado: Resultado, url: str) -> bool:
    nuxt_data = extrair_nuxt_data_olaclick(_http_html(url))
    _, auditoria = enriquecer_resultado_olaclick_variantes(resultado, nuxt_data)
    return (
        int(auditoria.get("produtos_vinculados") or 0) >= 1
        and int(auditoria.get("opcoes_materializadas") or 0) >= 2
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
            if _eh_anota(url):
                corrigidos = _sanear_vinhos_anota(atual)
                if corrigidos:
                    atual._leitor_universal = {
                        "plataforma": "Anota AI",
                        "saneamentos": ["vinho-falso-pizza"],
                    }
                    atual.avisos.insert(
                        0,
                        f"Anota AI: {corrigidos} vinho(s) reclassificado(s) como item regular após falso positivo de pizza comprovado na bateria real.",
                    )

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

            if _eh_olaclick(url):
                try:
                    if _enriquecer_olaclick_url(atual, url):
                        atual.avisos.insert(
                            0,
                            "Variantes Ola Click enriquecidas pelo estado Nuxt público validado, com vínculo por ID e preço final preservado por delta.",
                        )
                        return atual, "oficial+olaclick-nuxt"
                    atual.avisos.append(
                        "Ola Click: nenhuma escolha de variantes nomeadas suficientemente comprovada foi encontrada; o resultado oficial foi preservado."
                    )
                except Exception as exc:
                    atual.avisos.append(
                        f"Ola Click: enriquecimento de variantes indisponível ({type(exc).__name__}); o resultado oficial foi preservado."
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
