"""Exportacao controlada da previa universal V2.

So gera XLSX quando a validacao tecnica aprovou E o chamador passa
confirmacao explicita. Nao e usada pela main enquanto a V2 estiver em testes.
"""
from typing import Any, Dict, List

from models import Produto, GrupoOpcao, Resultado
from xlsx_writer import gerar_xlsx


def _produto(d: Dict[str, Any]) -> Produto:
    return Produto(
        codigo=str(d.get("codigo","") or ""),
        nome=str(d.get("nome","") or ""),
        descricao=str(d.get("descricao","") or ""),
        categoria=str(d.get("categoria","") or ""),
        imagem=str(d.get("imagem","") or ""),
        preco=float(d.get("preco",0) or 0),
        grupos=[str(x) for x in (d.get("grupos") or [])],
        pizza=bool(d.get("pizza",False)),
        combo=bool(d.get("combo",False)),
        metodo_preco_pizza=int(d.get("metodo_preco_pizza",0) or 0),
    )


def _grupo(d: Dict[str, Any]) -> GrupoOpcao:
    return GrupoOpcao(
        grupo_id=str(d.get("grupo_id","") or ""),
        tipo=int(d.get("tipo",1) or 1),
        grupo_nome=str(d.get("grupo_nome","") or ""),
        nome=str(d.get("nome","") or ""),
        imagem=str(d.get("imagem","") or ""),
        preco=float(d.get("preco",0) or 0),
        minimo=int(d.get("minimo",0) or 0),
        maximo=int(d.get("maximo",1) or 1),
        repetir=int(d.get("repetir",0) or 0),
        metodo_preco=int(d.get("metodo_preco",1) or 1),
    )


def montar_resultado_controlado(preview: Dict[str, Any]) -> Resultado:
    validacao=preview.get("validacao") or {}
    if not validacao.get("aprovado"):
        raise ValueError("Previa universal nao aprovada pela validacao tecnica.")

    itens=[]; pizzas=[]
    for d in preview.get("produtos") or []:
        p=_produto(d)
        if p.pizza:
            if int(p.metodo_preco_pizza or 0) == 0:
                raise ValueError(f"Pizza '{p.nome}' sem metodo de preco definido.")
            pizzas.append(p)
        else:
            itens.append(p)

    grupos=[_grupo(g) for g in (preview.get("grupos") or [])]
    return Resultado(
        itens=itens,
        pizzas=pizzas,
        grupos=grupos,
        origem=str(preview.get("url_final","") or "Leitor Universal V2"),
        avisos=list(preview.get("avisos") or []),
    )


def gerar_xlsx_universal_controlado(template_bytes: bytes, preview: Dict[str, Any], confirmar: bool = False) -> bytes:
    if not confirmar:
        raise PermissionError("Exportacao universal exige confirmacao explicita de teste controlado.")
    resultado=montar_resultado_controlado(preview)
    return gerar_xlsx(template_bytes, resultado)
