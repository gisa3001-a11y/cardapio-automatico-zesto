"""Regras conservadoras de pizza para o Leitor Universal V2.

Esta camada trabalha sobre a previa generica ja normalizada. Ela NAO libera XLSX
nem altera parsers oficiais. Apenas identifica provaveis pizzas e sugere o
metodo de preco com base em sinais do produto e dos grupos vinculados.
"""

from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Tuple


SABOR_TERMS = ("sabor", "sabores", "flavor", "flavours", "flavors")
TAMANHO_TERMS = ("tamanho", "tamanhos", "size", "sizes")
BORDA_TERMS = ("borda", "bordas", "crust")
PIZZA_TERMS = ("pizza", "pizzas", "pizzaria")

# Mantem os mesmos codigos de modelo ja usados no projeto:
# 0 = indefinido/nao confirmado
# 1 = preco base / regra simples
# 3 = maior valor entre sabores
METODO_INDEFINIDO = 0
METODO_BASE = 1
METODO_MAIOR_VALOR = 3


@dataclass
class DiagnosticoPizza:
    codigo: str
    nome: str
    pizza: bool
    confianca: str
    metodo_preco_pizza: int
    motivo: str
    grupos_sabor: List[str]
    grupos_tamanho: List[str]
    grupos_borda: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _norm(value: Any) -> str:
    return str(value or "").strip().lower()


def _contem(texto: str, termos) -> bool:
    t = _norm(texto)
    return any(term in t for term in termos)


def _grupos_por_produto(produto: Dict[str, Any], grupos: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    ids = {str(x) for x in (produto.get("grupos") or [])}
    if not ids:
        return []
    return [g for g in grupos if str(g.get("grupo_id", "")) in ids]


def _resumir_grupos(grupos_produto: List[Dict[str, Any]]) -> Tuple[List[str], List[str], List[str]]:
    sabores, tamanhos, bordas = [], [], []
    vistos = set()
    for g in grupos_produto:
        gid = str(g.get("grupo_id", ""))
        if not gid:
            continue
        chave = (gid, str(g.get("grupo_nome", "")))
        if chave in vistos:
            continue
        vistos.add(chave)
        nome = str(g.get("grupo_nome", ""))
        tipo = int(g.get("tipo", 1) or 1)
        if tipo == 2 or _contem(nome, SABOR_TERMS):
            sabores.append(gid)
        if _contem(nome, TAMANHO_TERMS):
            tamanhos.append(gid)
        if tipo == 3 or _contem(nome, BORDA_TERMS):
            bordas.append(gid)
    return sabores, tamanhos, bordas


def _precos_grupo(grupo_id: str, grupos: List[Dict[str, Any]]) -> List[float]:
    precos = []
    for g in grupos:
        if str(g.get("grupo_id", "")) != str(grupo_id):
            continue
        try:
            precos.append(float(g.get("preco", 0) or 0))
        except Exception:
            pass
    return precos


def diagnosticar_pizza(produto: Dict[str, Any], grupos: List[Dict[str, Any]]) -> DiagnosticoPizza:
    nome = str(produto.get("nome", "") or "")
    categoria = str(produto.get("categoria", "") or "")
    codigo = str(produto.get("codigo", "") or "")
    vinculados = _grupos_por_produto(produto, grupos)
    sabores, tamanhos, bordas = _resumir_grupos(vinculados)

    nome_pizza = _contem(nome, PIZZA_TERMS) or _contem(categoria, PIZZA_TERMS)
    tem_sabor = bool(sabores)
    tem_tamanho = bool(tamanhos)
    tem_borda = bool(bordas)

    if tem_sabor and (nome_pizza or tem_tamanho or tem_borda):
        pizza = True
        confianca = "alta"
        motivo = "Produto com grupo de sabores e sinais adicionais de pizza."
    elif nome_pizza and (tem_sabor or tem_tamanho or tem_borda):
        pizza = True
        confianca = "media"
        motivo = "Nome/categoria indica pizza e ha grupos compativeis."
    elif tem_sabor and len(vinculados) >= 2:
        pizza = True
        confianca = "media"
        motivo = "Ha grupo de sabores e mais de um grupo de configuracao."
    else:
        pizza = False
        confianca = "baixa"
        motivo = "Sinais insuficientes para classificar como pizza."

    metodo = METODO_INDEFINIDO
    if pizza:
        # Se sabores possuem precos diferentes, o universal nao assume media/soma.
        # A sugestao mais segura para previa e 'maior valor', mas continua marcada
        # como inferencia ate validacao da plataforma.
        precos_sabores = []
        for gid in sabores:
            precos_sabores.extend(_precos_grupo(gid, grupos))
        positivos = sorted({round(p, 2) for p in precos_sabores if p > 0})
        if len(positivos) >= 2:
            metodo = METODO_MAIOR_VALOR
            motivo += " Sabores possuem precos diferentes; sugerido maior valor."
        elif positivos:
            metodo = METODO_BASE
            motivo += " Sabores possuem preco uniforme/isolado; regra simples sugerida."
        else:
            metodo = METODO_INDEFINIDO
            motivo += " Nao ha evidencia suficiente para definir a regra de preco."

    return DiagnosticoPizza(
        codigo=codigo,
        nome=nome,
        pizza=pizza,
        confianca=confianca,
        metodo_preco_pizza=metodo,
        motivo=motivo,
        grupos_sabor=sabores,
        grupos_tamanho=tamanhos,
        grupos_borda=bordas,
    )


def aplicar_regras_pizza(produtos: List[Dict[str, Any]], grupos: List[Dict[str, Any]]):
    saida_produtos = []
    diagnosticos = []
    for produto in produtos:
        p = dict(produto)
        diag = diagnosticar_pizza(p, grupos)
        diagnosticos.append(diag.to_dict())
        if diag.pizza:
            p["pizza"] = True
            p["metodo_preco_pizza"] = diag.metodo_preco_pizza
        saida_produtos.append(p)
    return saida_produtos, diagnosticos
