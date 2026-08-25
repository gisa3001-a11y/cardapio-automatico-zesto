"""Ponte segura entre o Leitor Universal V2 e o app atual.

Converte uma previa universal aprovada para os modelos ja usados por validator.py
and xlsx_writer.py. Nao altera o fluxo principal do Streamlit e nao faz exportacao
sem validacao tecnica aprovada.
"""
from typing import Any, Dict

from models import GrupoOpcao, Produto, Resultado


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _produto(d: Dict[str, Any], forcar_pizza: bool = False) -> Produto:
    pizza = bool(d.get("pizza")) or forcar_pizza
    return Produto(
        codigo=str(d.get("codigo") or ""),
        nome=str(d.get("nome") or "").strip(),
        descricao=str(d.get("descricao") or "").strip(),
        categoria=str(d.get("categoria") or "").strip(),
        imagem=str(d.get("imagem") or "").strip(),
        preco=_as_float(d.get("preco"), 0.0),
        grupos=[str(x) for x in (d.get("grupos") or []) if str(x)],
        pizza=pizza,
        combo=bool(d.get("combo")),
        metodo_preco_pizza=_as_int(d.get("metodo_preco_pizza"), 0),
    )


def _grupo(d: Dict[str, Any]) -> GrupoOpcao:
    return GrupoOpcao(
        grupo_id=str(d.get("grupo_id") or ""),
        tipo=_as_int(d.get("tipo"), 1) or 1,
        grupo_nome=str(d.get("grupo_nome") or "").strip(),
        nome=str(d.get("nome") or "").strip(),
        imagem=str(d.get("imagem") or "").strip(),
        preco=_as_float(d.get("preco"), 0.0),
        minimo=_as_int(d.get("minimo"), 0),
        maximo=_as_int(d.get("maximo"), 1),
        repetir=_as_int(d.get("repetir"), 0),
        metodo_preco=_as_int(d.get("metodo_preco"), 1) or 1,
    )


def converter_previa_para_resultado(previa, exigir_aprovacao: bool = True) -> Resultado:
    """Converte ``ResultadoPreviaUniversal`` para ``models.Resultado``.

    A integracao e deliberadamente fail-closed: por padrao uma previa que nao passou
    na validacao universal nao pode virar Resultado exportavel.
    """
    validacao = getattr(previa, "validacao", None) or {}
    if exigir_aprovacao and not bool(validacao.get("aprovado")):
        erros = validacao.get("erros") or []
        detalhe = "; ".join(str(x) for x in erros[:4]) or "validacao universal reprovada"
        raise ValueError("Previa universal ainda nao pode ser integrada ao XLSX: " + detalhe)

    grupos = [_grupo(g) for g in (getattr(previa, "grupos", None) or [])]

    pizza_codes = {
        str(p.get("codigo") or "")
        for p in (getattr(previa, "pizzas", None) or [])
        if isinstance(p, dict)
    }
    pizza_map = {
        str(p.get("codigo") or ""): p
        for p in (getattr(previa, "pizzas", None) or [])
        if isinstance(p, dict)
    }

    itens = []
    pizzas = []
    for d in (getattr(previa, "produtos", None) or []):
        if not isinstance(d, dict):
            continue
        codigo = str(d.get("codigo") or "")
        if bool(d.get("pizza")) or codigo in pizza_codes:
            mesclado = dict(d)
            mesclado.update(pizza_map.get(codigo) or {})
            pizzas.append(_produto(mesclado, forcar_pizza=True))
        else:
            itens.append(_produto(d))

    avisos = list(getattr(previa, "avisos", None) or [])
    for aviso in validacao.get("avisos") or []:
        if aviso not in avisos:
            avisos.append(str(aviso))

    return Resultado(
        itens=itens,
        pizzas=pizzas,
        grupos=grupos,
        origem=f"Leitor Universal V2 • {getattr(previa, 'fonte', '')}".strip(),
        avisos=avisos,
    )
