"""Detector estrutural experimental do Leitor Universal V2.

Nao gera XLSX. Apenas coleta sinais e candidatos de paginas desconhecidas.
Mantido isolado da main ate validacao.
"""
from dataclasses import dataclass, asdict
import json
import re
from typing import Any, Dict, List
from urllib.parse import urljoin

import requests

PRECO_RE = re.compile(r"(?:R\$\s*)?\d{1,4}[\.,]\d{2}")
CHAVES_NOME = {"name", "nome", "title", "titulo", "product", "produto", "description", "descricao"}
CHAVES_PRECO = {"price", "preco", "valor", "amount", "saleprice", "promotionalprice"}
CHAVES_IMG = {"image", "imagem", "photo", "foto", "imageurl", "image_url", "urlimagem"}
CHAVES_GRUPO = {"options", "optiongroups", "option_groups", "addons", "adicionais", "complements", "complementos", "extras"}

@dataclass
class Candidato:
    origem: str
    nome: str = ""
    preco: str = ""
    imagem: str = ""
    tem_adicionais: bool = False
    score: int = 0


def _walk(obj: Any, origem: str, out: List[Candidato], limite: int = 5000):
    if len(out) >= limite:
        return
    if isinstance(obj, dict):
        lower = {str(k).lower().replace("_", ""): v for k, v in obj.items()}
        nome = preco = imagem = ""
        grupos = False
        for k, v in lower.items():
            if k in {x.replace("_", "") for x in CHAVES_NOME} and isinstance(v, (str, int, float)) and not nome:
                nome = str(v).strip()
            if k in {x.replace("_", "") for x in CHAVES_PRECO} and isinstance(v, (str, int, float)) and not preco:
                preco = str(v).strip()
            if k in {x.replace("_", "") for x in CHAVES_IMG} and isinstance(v, str) and not imagem:
                imagem = v.strip()
            if k in {x.replace("_", "") for x in CHAVES_GRUPO} and isinstance(v, (list, dict)):
                grupos = True
        score = (3 if nome else 0) + (4 if preco else 0) + (2 if imagem else 0) + (2 if grupos else 0)
        if nome and (preco or imagem or grupos):
            out.append(Candidato(origem, nome[:300], preco[:80], imagem[:1000], grupos, score))
        for k, v in obj.items():
            _walk(v, f"{origem}.{k}", out, limite)
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:1000]):
            _walk(v, f"{origem}[{i}]", out, limite)


def _json_embutido(html: str) -> List[Any]:
    achados = []
    padroes = [
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        r'<script[^>]+type=["\']application/json["\'][^>]*>(.*?)</script>',
        r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
    ]
    for padrao in padroes:
        for bruto in re.findall(padrao, html, flags=re.I | re.S):
            try:
                achados.append(json.loads(bruto.strip()))
            except Exception:
                pass
    return achados


def analisar_estrutura(url: str, timeout: int = 20) -> Dict[str, Any]:
    headers = {"User-Agent": "Mozilla/5.0 (compatible; CardapioUniversalV2/1.0)"}
    r = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
    r.raise_for_status()
    html = r.text
    candidatos: List[Candidato] = []
    jsons = _json_embutido(html)
    for i, obj in enumerate(jsons):
        _walk(obj, f"json[{i}]", candidatos)

    # Sinais HTML sem assumir uma plataforma.
    precos_html = PRECO_RE.findall(html)
    imagens = re.findall(r'<img[^>]+(?:src|data-src)=["\']([^"\']+)', html, flags=re.I)
    imagens = [urljoin(r.url, x) for x in imagens[:200]]

    candidatos.sort(key=lambda x: x.score, reverse=True)
    fortes = [c for c in candidatos if c.score >= 7]
    if len(fortes) >= 5:
        confianca = "alta"
    elif len(fortes) >= 2 or (len(precos_html) >= 5 and len(imagens) >= 3):
        confianca = "media"
    else:
        confianca = "baixa"

    return {
        "url_solicitada": url,
        "url_final": r.url,
        "status_http": r.status_code,
        "content_type": r.headers.get("content-type", ""),
        "tamanho_html": len(html),
        "jsons_embutidos": len(jsons),
        "precos_encontrados_html": len(precos_html),
        "imagens_encontradas_html": len(imagens),
        "candidatos": [asdict(c) for c in candidatos[:100]],
        "candidatos_fortes": len(fortes),
        "confianca": confianca,
        "pode_gerar_xlsx": False,
        "observacao": "Diagnostico somente; exige validacao antes de converter automaticamente.",
    }
