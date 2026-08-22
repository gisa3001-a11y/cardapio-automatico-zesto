"""Detector de estrutura para o Leitor Universal V2.

Objetivo: analisar URLs desconhecidas sem alterar os parsers oficiais.
Esta fase identifica sinais de cardapio em HTML e JSON publico e retorna
um diagnostico com nivel de confianca. Nao gera XLSX sozinho.
"""

from dataclasses import dataclass, asdict
import json
import re
from typing import Any, Dict, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup


HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/151 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json;q=0.8,*/*;q=0.7",
}

CHAVES_PRODUTO = {"product", "products", "produto", "produtos", "item", "items", "name", "nome", "title", "titulo"}
CHAVES_PRECO = {"price", "preco", "preço", "value", "valor", "amount", "saleprice", "sale_price", "promotionalprice"}
CHAVES_IMAGEM = {"image", "imagem", "photo", "foto", "imageurl", "image_url", "coverimageurl", "src"}
CHAVES_CATEGORIA = {"category", "categories", "categoria", "categorias", "section", "sections"}
CHAVES_GRUPO = {"options", "optiongroups", "option_groups", "modifiers", "modifiergroups", "extras", "addons", "add_ons", "complements", "complementos", "choices", "variations"}

PRECO_RE = re.compile(r"(?:R\$\s*)?\d{1,4}(?:[\.,]\d{2})")


@dataclass
class CandidatoEstrutura:
    origem: str
    score: int
    sinais: List[str]
    amostra: Optional[str] = None


@dataclass
class DiagnosticoEstrutura:
    url: str
    status_http: Optional[int]
    content_type: str
    titulo: str
    score_total: int
    confianca: str
    candidatos: List[CandidatoEstrutura]
    sinais_globais: List[str]
    erro: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["candidatos"] = [asdict(c) for c in self.candidatos]
        return d


def _norm_key(k: Any) -> str:
    return str(k or "").strip().lower().replace("-", "_").replace(" ", "")


def _score_dict(obj: Dict[str, Any]) -> Tuple[int, List[str]]:
    keys = {_norm_key(k) for k in obj.keys()}
    score = 0
    sinais: List[str] = []

    if keys & CHAVES_PRODUTO:
        score += 2
        sinais.append("nome/produto")
    if keys & CHAVES_PRECO:
        score += 3
        sinais.append("preco")
    if keys & CHAVES_IMAGEM:
        score += 1
        sinais.append("imagem")
    if keys & CHAVES_CATEGORIA:
        score += 2
        sinais.append("categoria")
    if keys & CHAVES_GRUPO:
        score += 3
        sinais.append("grupos/adicionais")

    return score, sinais


def _walk_json(value: Any, path: str = "$", out: Optional[List[CandidatoEstrutura]] = None, limite: int = 80) -> List[CandidatoEstrutura]:
    if out is None:
        out = []
    if len(out) >= limite:
        return out

    if isinstance(value, dict):
        score, sinais = _score_dict(value)
        if score >= 4:
            amostra = None
            try:
                amostra = json.dumps(value, ensure_ascii=False, default=str)[:500]
            except Exception:
                pass
            out.append(CandidatoEstrutura(origem=path, score=score, sinais=sinais, amostra=amostra))

        for k, v in list(value.items())[:100]:
            _walk_json(v, f"{path}.{k}", out, limite)
            if len(out) >= limite:
                break

    elif isinstance(value, list):
        for i, v in enumerate(value[:100]):
            _walk_json(v, f"{path}[{i}]", out, limite)
            if len(out) >= limite:
                break

    return out


def _extrair_json_scripts(soup: BeautifulSoup) -> List[Tuple[str, Any]]:
    encontrados: List[Tuple[str, Any]] = []
    for i, script in enumerate(soup.find_all("script")):
        texto = script.string or script.get_text("", strip=False) or ""
        tipo = (script.get("type") or "").lower()
        if not texto.strip():
            continue

        if "json" in tipo:
            try:
                encontrados.append((f"script[{i}]/{tipo or 'json'}", json.loads(texto)))
                continue
            except Exception:
                pass

        # Frameworks frequentemente embutem JSON bruto em tags de script.
        if texto.lstrip().startswith(("{", "[")):
            try:
                encontrados.append((f"script[{i}]/inline-json", json.loads(texto)))
            except Exception:
                pass

    return encontrados


def _score_html(soup: BeautifulSoup) -> Tuple[int, List[str]]:
    sinais: List[str] = []
    score = 0
    texto = " ".join(soup.stripped_strings)

    if len(PRECO_RE.findall(texto)) >= 3:
        score += 3
        sinais.append("multiplos precos visiveis")

    imgs = soup.find_all("img")
    if len(imgs) >= 3:
        score += 1
        sinais.append("multiplas imagens")

    nomes_classes = " ".join(
        " ".join(tag.get("class") or []) for tag in soup.find_all(True)[:1500]
    ).lower()
    for termo, pontos, rotulo in [
        ("product", 2, "classes de produto"),
        ("produto", 2, "classes de produto"),
        ("category", 2, "classes de categoria"),
        ("categoria", 2, "classes de categoria"),
        ("modifier", 3, "classes de adicionais"),
        ("option", 2, "classes de opcoes"),
        ("addon", 3, "classes de adicionais"),
    ]:
        if termo in nomes_classes and rotulo not in sinais:
            score += pontos
            sinais.append(rotulo)

    return score, sinais


def _nivel_confianca(score: int, candidatos: List[CandidatoEstrutura]) -> str:
    melhor = max((c.score for c in candidatos), default=0)
    if score >= 12 and melhor >= 7:
        return "alta"
    if score >= 7 or melhor >= 6:
        return "media"
    return "baixa"


def diagnosticar_estrutura(url: str, timeout: int = 25) -> DiagnosticoEstrutura:
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
        content_type = r.headers.get("content-type", "")
        status = r.status_code
        r.raise_for_status()

        candidatos: List[CandidatoEstrutura] = []
        sinais_globais: List[str] = []
        titulo = ""
        score_total = 0

        if "json" in content_type.lower():
            data = r.json()
            candidatos = _walk_json(data)
            score_total += max((c.score for c in candidatos), default=0) + min(len(candidatos), 5)
            sinais_globais.append("resposta JSON direta")
        else:
            soup = BeautifulSoup(r.text, "html.parser")
            titulo = (soup.title.string.strip() if soup.title and soup.title.string else "")
            score_html, sinais_html = _score_html(soup)
            score_total += score_html
            sinais_globais.extend(sinais_html)

            for origem, payload in _extrair_json_scripts(soup):
                locais = _walk_json(payload, path=origem)
                candidatos.extend(locais)

            if candidatos:
                score_total += max(c.score for c in candidatos)
                score_total += min(len(candidatos), 5)
                sinais_globais.append("JSON estruturado embutido")

        candidatos = sorted(candidatos, key=lambda c: c.score, reverse=True)[:20]
        confianca = _nivel_confianca(score_total, candidatos)

        return DiagnosticoEstrutura(
            url=r.url,
            status_http=status,
            content_type=content_type,
            titulo=titulo,
            score_total=score_total,
            confianca=confianca,
            candidatos=candidatos,
            sinais_globais=sinais_globais,
        )

    except Exception as exc:
        return DiagnosticoEstrutura(
            url=url,
            status_http=None,
            content_type="",
            titulo="",
            score_total=0,
            confianca="baixa",
            candidatos=[],
            sinais_globais=[],
            erro=str(exc),
        )
