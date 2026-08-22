"""Resolucao conservadora de preco para o Leitor Universal V2.

Corrige apenas casos em que o produto veio com preco zero e existe evidencia
forte de que o valor real esta em um grupo de tamanho/sabor/opcoes vinculadas.
Nao inventa preco e nao libera XLSX sozinho.
"""
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional

PRICE_GROUP_TERMS = ("tamanho", "size", "porcao", "porção", "peso", "volume", "sabor", "flavor")

@dataclass
class DiagnosticoPreco:
    codigo: str
    nome: str
    preco_original: float
    preco_sugerido: Optional[float]
    resolvido: bool
    confianca: str
    fonte_grupo: str
    motivo: str

    def to_dict(self):
        return asdict(self)

def _norm(v: Any) -> str:
    return str(v or "").strip().lower()

def _grupos_do_produto(produto: Dict[str, Any], grupos: List[Dict[str, Any]]):
    ids = {str(x) for x in (produto.get("grupos") or [])}
    return [g for g in grupos if str(g.get("grupo_id", "")) in ids]

def _precos_positivos(linhas: List[Dict[str, Any]]) -> List[float]:
    out=[]
    for g in linhas:
        try:
            p=float(g.get("preco",0) or 0)
            if 0 < p <= 5000:
                out.append(round(p,2))
        except Exception:
            pass
    return out

def resolver_preco_zero(produto: Dict[str, Any], grupos: List[Dict[str, Any]]) -> DiagnosticoPreco:
    codigo=str(produto.get("codigo","") or "")
    nome=str(produto.get("nome","") or "")
    try:
        original=float(produto.get("preco",0) or 0)
    except Exception:
        original=0.0

    if original > 0:
        return DiagnosticoPreco(codigo,nome,original,original,False,"alta","","Produto ja possui preco base positivo.")

    vinculados=_grupos_do_produto(produto,grupos)
    por_grupo={}
    for g in vinculados:
        gid=str(g.get("grupo_id","") or "")
        por_grupo.setdefault(gid,[]).append(g)

    candidatos=[]
    for gid, linhas in por_grupo.items():
        nome_grupo=str(linhas[0].get("grupo_nome","") or "")
        precos=_precos_positivos(linhas)
        if not precos:
            continue
        eh_preco_base=any(t in _norm(nome_grupo) for t in PRICE_GROUP_TERMS)
        minimo=min(precos)
        candidatos.append((eh_preco_base,minimo,gid,nome_grupo,len(set(precos))))

    fortes=[c for c in candidatos if c[0]]
    if len(fortes)==1:
        _, valor, gid, nome_grupo, variacoes=fortes[0]
        return DiagnosticoPreco(codigo,nome,original,valor,True,"alta",gid,
            f"Preco zero resolvido pelo menor valor positivo do grupo '{nome_grupo}' ({variacoes} valor(es) distinto(s)).")

    if len(fortes)>1:
        valores={c[1] for c in fortes}
        if len(valores)==1:
            valor=next(iter(valores))
            return DiagnosticoPreco(codigo,nome,original,valor,True,"media","multiplos",
                "Multiplos grupos de preco-base apontam para o mesmo menor valor positivo.")
        return DiagnosticoPreco(codigo,nome,original,None,False,"baixa","",
            "Preco zero com mais de um grupo candidato e valores divergentes; exige validacao.")

    if len(candidatos)==1:
        _, valor, gid, nome_grupo, _ = candidatos[0]
        return DiagnosticoPreco(codigo,nome,original,valor,False,"media",gid,
            f"Ha um unico grupo com valores positivos ('{nome_grupo}'), mas o tipo do grupo nao confirma preco-base.")

    return DiagnosticoPreco(codigo,nome,original,None,False,"baixa","",
        "Nenhuma evidencia forte para substituir o preco zero.")

def aplicar_resolucao_precos(produtos: List[Dict[str, Any]], grupos: List[Dict[str, Any]]):
    saida=[]; diags=[]
    for produto in produtos:
        p=dict(produto)
        d=resolver_preco_zero(p,grupos)
        if d.resolvido and d.preco_sugerido is not None:
            p["preco"] = d.preco_sugerido
            p["_preco_resolvido"] = True
            p["_preco_original"] = d.preco_original
        saida.append(p); diags.append(d.to_dict())
    return saida, diags
