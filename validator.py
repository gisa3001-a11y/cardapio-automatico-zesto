from models import Resultado
from utils import parece_pizza

def validar(resultado: Resultado):
    erros=[]
    avisos=[]

    # Pizza não pode vazar para Item Regular.
    novos_itens=[]
    for p in resultado.itens:
        if p.combo:
            novos_itens.append(p)
            continue
        if p.pizza or parece_pizza(p.nome,p.categoria,p.descricao):
            p.pizza=True
            resultado.pizzas.append(p)
        else:
            novos_itens.append(p)
    resultado.itens=novos_itens

    # Dedupe pizza / item.
    pizza_keys={(p.nome.lower(),p.categoria.lower()) for p in resultado.pizzas}
    resultado.itens=[p for p in resultado.itens if (p.nome.lower(),p.categoria.lower()) not in pizza_keys]

    # Grupos com pelo menos uma opção.
    grupos_por_id={}
    for g in resultado.grupos:
        grupos_por_id.setdefault(str(g.grupo_id),[]).append(g)
    ids_validos={gid for gid,opts in grupos_por_id.items() if opts}

    # Vínculos inexistentes bloqueiam.
    for p in resultado.itens+resultado.pizzas:
        bad=[str(gid) for gid in p.grupos if str(gid) not in ids_validos]
        if bad:
            erros.append(f'Produto "{p.nome}" aponta para grupo(s) inexistente(s): {", ".join(bad)}')
        p.grupos=[str(gid) for gid in p.grupos if str(gid) in ids_validos]

    usados={gid for p in resultado.itens+resultado.pizzas for gid in p.grupos}
    resultado.grupos=[g for g in resultado.grupos if str(g.grupo_id) in usados]

    # Validação estrutural adicional.
    codigos={}
    for p in resultado.itens+resultado.pizzas:
        codigos.setdefault(str(p.codigo),[]).append(p.nome)
    duplicados={k:v for k,v in codigos.items() if k and len(v)>1}
    for codigo,nomes in duplicados.items():
        erros.append(
            f'Código de produto duplicado "{codigo}": {", ".join(nomes)}'
        )

    # Não permite duplicar a mesma opção dentro do mesmo grupo.
    opcoes_vistas=set()
    for g in resultado.grupos:
        chave=(str(g.grupo_id), str(g.nome).strip().lower(), round(float(g.preco or 0),6))
        if chave in opcoes_vistas:
            erros.append(
                f'Opção duplicada no grupo {g.grupo_id}: "{g.nome}" ({g.preco}).'
            )
        opcoes_vistas.add(chave)

    # Auditoria estrita específica do Cardápio Web.
    audit=getattr(resultado,"_cardapioweb_audit",None)
    if audit:
        esperado_prod=int(audit.get("produtos_active_api") or 0)
        saida_prod=len(resultado.itens)+len(resultado.pizzas)
        if esperado_prod != saida_prod:
            erros.append(
                f"Cardápio Web: API retornou {esperado_prod} produtos ACTIVE, "
                f"mas a saída contém {saida_prod}."
            )

        esperado_grupos=int(audit.get("grupos_ids_unicos_api") or 0)
        saida_grupos=len({str(g.grupo_id) for g in resultado.grupos})
        if esperado_grupos != saida_grupos:
            erros.append(
                f"Cardápio Web: API contém {esperado_grupos} grupos únicos, "
                f"mas a saída contém {saida_grupos}."
            )

        esperado_opcoes=int(audit.get("opcoes_unicas_por_grupo_api") or 0)
        saida_opcoes=len(resultado.grupos)
        if esperado_opcoes != saida_opcoes:
            erros.append(
                f"Cardápio Web: API contém {esperado_opcoes} opções únicas por grupo, "
                f"mas a saída contém {saida_opcoes}."
            )

        esperado_vinculos=int(audit.get("vinculos_total_api") or 0)
        saida_vinculos=sum(
            len(p.grupos or []) for p in resultado.itens+resultado.pizzas
        )
        if esperado_vinculos != saida_vinculos:
            erros.append(
                f"Cardápio Web: API contém {esperado_vinculos} vínculos produto→grupo, "
                f"mas a saída contém {saida_vinculos}."
            )

        for conflito in (audit.get("conflitos_grupo") or []):
            erros.append("Cardápio Web: "+str(conflito))

        # Vínculo produto -> grupo deve ser idêntico ao JSON da API.
        vinc_api=audit.get("vinculos_produto_grupo_api") or {}
        vinc_saida={
            str(p.codigo):[str(x) for x in (p.grupos or [])]
            for p in resultado.itens+resultado.pizzas
        }
        for pid,esperados in vinc_api.items():
            # produtos sem ID recebem chave sintética na auditoria e não entram aqui.
            if str(pid).startswith("sem-id:"):
                continue
            obtidos=vinc_saida.get(str(pid))
            if obtidos is None:
                erros.append(f"Cardápio Web: produto ID {pid} desapareceu da saída.")
                continue
            if list(esperados) != list(obtidos):
                erros.append(
                    f"Cardápio Web: vínculos divergentes no produto ID {pid}. "
                    f"API={','.join(esperados)} | saída={','.join(obtidos)}"
                )

    # FINAL: alerta de baixa confiança para resultados de fallback/HTML.
    origem=(resultado.origem or "").lower()
    total_prod=len(resultado.itens)+len(resultado.pizzas)
    if ("html universal" in origem or "playwright" in origem or "rapidfood" in origem or "byfood" in origem):
        if total_prod <= 2:
            erros.append(
                "FINAL: resultado de baixa confiança (2 produtos ou menos em parser HTML/fallback). "
                "Use o diagnóstico de rede antes de importar."
            )
        if total_prod and not any(p.categoria for p in resultado.itens+resultado.pizzas):
            avisos.append("FINAL: nenhum produto possui categoria; confira o diagnóstico de rede.")
        if total_prod and not resultado.grupos:
            avisos.append("FINAL: nenhum adicional foi encontrado; a plataforma pode exigir parser/API específico.")

    # Preços
    for p in resultado.itens+resultado.pizzas:
        if p.preco < 0:
            erros.append(f'Preço negativo em "{p.nome}".')
        if p.preco == 0:
            avisos.append(f'Preço zero em "{p.nome}".')

    if not resultado.itens and not resultado.pizzas:
        erros.append("Nenhum produto foi reconhecido.")

    return erros, avisos
