"""Validacao final da previa universal antes de qualquer liberacao de XLSX."""
from dataclasses import dataclass, asdict
from typing import Any, Dict, List
from urllib.parse import urlparse

@dataclass
class ValidacaoUniversal:
    aprovado: bool
    score: int
    erros: List[str]
    avisos: List[str]
    metricas: Dict[str, Any]

    def to_dict(self):
        d=asdict(self)
        d["pode_gerar_xlsx"] = bool(self.aprovado)
        return d

def _url_http(v: str) -> bool:
    if not v: return False
    try:
        p=urlparse(v)
        return p.scheme in ("http","https") and bool(p.netloc)
    except Exception:
        return False

def validar_previa(produtos: List[Dict[str, Any]], grupos: List[Dict[str, Any]], pizzas: List[Dict[str, Any]], confianca: str):
    erros=[]; avisos=[]; score=0
    total=len(produtos)
    if total < 3:
        erros.append("Poucos produtos confiaveis para liberar exportacao universal.")
    else:
        score += 25

    nomes=[str(p.get("nome","") or "").strip() for p in produtos]
    nomes_validos=sum(1 for n in nomes if len(n)>=2)
    if total and nomes_validos/total >= .95: score += 15
    else: erros.append("Existem produtos sem nome valido.")

    precos=[]; zeros=0
    for p in produtos:
        try: v=float(p.get("preco",0) or 0)
        except Exception: v=-1
        precos.append(v)
        if v == 0: zeros += 1
        if v < 0 or v > 5000: erros.append(f"Preco fora da faixa esperada: {p.get('nome','item')}")
    if total and zeros == 0: score += 20
    elif zeros <= max(1,total//10):
        score += 8; avisos.append(f"{zeros} produto(s) ainda com preco zero.")
    else: erros.append("Muitos produtos ainda estao com preco zero.")

    imagens=sum(1 for p in produtos if _url_http(str(p.get("imagem","") or "")))
    if total and imagens/total >= .5: score += 10
    elif imagens: score += 5; avisos.append("Parte dos produtos nao possui imagem valida.")
    else: avisos.append("Nenhuma imagem valida foi confirmada.")

    ids_prod={str(p.get("codigo","") or "") for p in produtos}
    ids_grupos={str(g.get("grupo_id","") or "") for g in grupos}
    referencias_invalidas=0
    for p in produtos:
        for gid in p.get("grupos") or []:
            if str(gid) not in ids_grupos: referencias_invalidas += 1
    if referencias_invalidas == 0: score += 15
    else: erros.append(f"{referencias_invalidas} referencia(s) de grupo sem correspondencia.")

    grupos_invalidos=0
    for g in grupos:
        try:
            mn=int(g.get("minimo",0) or 0); mx=int(g.get("maximo",1) or 1)
            pr=float(g.get("preco",0) or 0)
        except Exception:
            grupos_invalidos += 1; continue
        if mn < 0 or mx < mn or pr < 0 or pr > 5000: grupos_invalidos += 1
    if grupos_invalidos == 0: score += 10
    else: erros.append(f"{grupos_invalidos} linha(s) de adicional com regra invalida.")

    pizza_indef=sum(1 for p in pizzas if int(p.get("metodo_preco_pizza",0) or 0) == 0)
    if pizza_indef:
        erros.append(f"{pizza_indef} pizza(s) ainda sem metodo de preco definido.")
    else: score += 10

    if confianca == "alta": score += 5
    elif confianca == "baixa": erros.append("Confianca estrutural baixa.")

    aprovado = score >= 85 and not erros
    if aprovado:
        avisos.append("Previa passou pela validacao tecnica; ainda requer teste controlado antes de ir para a main.")
    return ValidacaoUniversal(aprovado,score,erros,avisos,{"produtos":total,"grupos":len(ids_grupos),"pizzas":len(pizzas),"imagens_validas":imagens,"precos_zero":zeros,"codigos_produto":len(ids_prod)})
