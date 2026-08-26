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

def validar_previa(produtos: List[Dict[str, Any]], grupos: List[Dict[str, Any]], pizzas: List[Dict[str, Any]], confianca: str, min_produtos: int = 3):
    erros=[]; avisos=[]; score=0
    total=len(produtos)
    if total < max(1, int(min_produtos or 1)):
        erros.append("Poucos produtos confiaveis para liberar exportacao universal.")
    else:
        score += 25

    nomes=[str(p.get("nome","") or "").strip() for p in produtos]
    nomes_validos=sum(1 for n in nomes if len(n)>=2)
    if total and nomes_validos/total >= .95: score += 15
    else: erros.append("Existem produtos sem nome valido.")

    ids_grupos={str(g.get("grupo_id","") or "") for g in grupos}
    grupos_com_preco_positivo=set()
    for g in grupos:
        try:
            gid=str(g.get("grupo_id","") or "")
            preco_g=float(g.get("preco",0) or 0)
        except Exception:
            continue
        if gid and preco_g > 0:
            grupos_com_preco_positivo.add(gid)

    pizzas_com_preco_estruturado={
        str(p.get("codigo","") or "")
        for p in pizzas
        if int(p.get("metodo_preco_pizza",0) or 0) > 0
    }

    precos=[]; zeros=0; zeros_estruturados=0; zeros_pendentes=0
    for p in produtos:
        try: v=float(p.get("preco",0) or 0)
        except Exception: v=-1
        precos.append(v)
        if v == 0:
            zeros += 1
            gids={str(gid) for gid in (p.get("grupos") or [])}
            codigo=str(p.get("codigo","") or "")
            estruturado=bool(gids & grupos_com_preco_positivo) or codigo in pizzas_com_preco_estruturado
            if estruturado:
                zeros_estruturados += 1
            else:
                zeros_pendentes += 1
        if v < 0 or v > 5000: erros.append(f"Preco fora da faixa esperada: {p.get('nome','item')}")
    if total and zeros_pendentes == 0:
        score += 20
        if zeros_estruturados:
            avisos.append(f"{zeros_estruturados} produto(s) com preco base zero possuem preco estruturado em grupo/pizza.")
    elif zeros_pendentes <= max(1,total//10):
        score += 8; avisos.append(f"{zeros_pendentes} produto(s) ainda com preco zero sem resolucao estrutural.")
        if zeros_estruturados:
            avisos.append(f"{zeros_estruturados} produto(s) com preco base zero possuem preco estruturado em grupo/pizza.")
    else: erros.append("Muitos produtos ainda estao com preco zero sem resolucao estrutural.")

    # Foto e importante para qualidade do cadastro, mas a ausencia dela nao torna
    # nome/preco/categoria estruturalmente invalidos. Mantemos alerta explicito e
    # uma pontuacao parcial para nao transformar cardapios sem foto em falha tecnica.
    imagens=sum(1 for p in produtos if _url_http(str(p.get("imagem","") or "")))
    if total and imagens/total >= .5:
        score += 10
    elif imagens:
        score += 5; avisos.append("Parte dos produtos nao possui imagem valida.")
    else:
        score += 5; avisos.append("Nenhuma imagem valida foi confirmada; exportacao deve sinalizar fotos ausentes.")

    ids_prod={str(p.get("codigo","") or "") for p in produtos}
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
    return ValidacaoUniversal(aprovado,score,erros,avisos,{"produtos":total,"grupos":len(ids_grupos),"pizzas":len(pizzas),"imagens_validas":imagens,"precos_zero":zeros,"precos_zero_estruturados":zeros_estruturados,"precos_zero_pendentes":zeros_pendentes,"codigos_produto":len(ids_prod)})
