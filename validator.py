import re

from models import Resultado
from utils import parece_pizza


def _preservar_regular_saneado_universal(resultado: Resultado, produto) -> bool:
    """Evita que o validator desfaça saneamentos comprovados do Universal V2.

    O roteador universal já corrige dois falsos positivos específicos e validados
    com dados reais: vinhos do Anota AI cuja categoria vem marcada como pizza e o
    produto Pastel do Ola Click cuja descrição lista "pizza" apenas como sabor.
    Depois disso, ``validar`` não deve reclassificar esses mesmos itens usando a
    heurística genérica de nome/categoria/descrição.

    A exceção só vale quando o Resultado veio do Leitor Universal V2, o produto já
    está explicitamente como regular e corresponde aos mesmos critérios restritos
    usados pelo saneamento. Parsers/Resultados fora desse fluxo permanecem com o
    comportamento anterior.
    """
    if bool(getattr(produto, "pizza", False)):
        return False

    meta = getattr(resultado, "_leitor_universal", None) or {}
    plataforma = str(meta.get("plataforma") or "")
    nome = str(getattr(produto, "nome", "") or "")
    categoria = str(getattr(produto, "categoria", "") or "")

    if plataforma == "Anota AI":
        texto = f"{nome} {categoria}"
        eh_vinho = bool(re.search(r"\bvinho(?:s)?\b", texto, re.IGNORECASE))
        # O saneamento do roteador só mantém como pizza quando o próprio nome
        # possui evidência real. Categoria/descrição podem estar contaminadas.
        return eh_vinho and not parece_pizza(nome, "", "")

    if plataforma == "Ola Click":
        eh_pastel = bool(re.search(r"\bpast(?:el|eis)\b", nome, re.IGNORECASE))
        # "Pastel de Pizza" e pastel em categoria realmente de pizzas continuam
        # elegíveis à heurística; só o caso com pizza apenas na descrição é salvo.
        return eh_pastel and not parece_pizza(nome, categoria, "")

    return False


def _chave_funcional_opcao(grupo):
    """Identidade estrutural de uma opção dentro de um grupo.

    Nome e preço iguais não bastam para declarar duplicidade: em cardápios reais a
    mesma opção pode reaparecer com função/regras distintas. A chave completa serve
    apenas para detectar repetições realmente idênticas e avisar sem apagar a fonte.
    """
    return (
        str(grupo.grupo_id),
        str(grupo.nome).strip().lower(),
        round(float(grupo.preco or 0), 6),
        int(getattr(grupo, "tipo", 1) or 1),
        str(getattr(grupo, "grupo_nome", "") or "").strip().lower(),
        int(getattr(grupo, "minimo", 0) or 0),
        int(getattr(grupo, "maximo", 1) or 1),
        int(getattr(grupo, "repetir", 0) or 0),
        int(getattr(grupo, "metodo_preco", 1) or 1),
    )


def validar(resultado: Resultado):
    erros=[]
    avisos=[]

    # Pizza não pode vazar para Item Regular.
    novos_itens=[]
    for p in resultado.itens:
        if p.combo:
            novos_itens.append(p)
            continue
        if _preservar_regular_saneado_universal(resultado, p):
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

    # Repetições de opções da própria fonte são preservadas. Mesmo quando todos os
    # campos estruturais coincidem, isso não prova erro de leitura nem torna o XLSX
    # inseguro. Avisamos para auditoria, mas não deduplicamos e não bloqueamos.
    opcoes_vistas=set()
    for g in resultado.grupos:
        chave=_chave_funcional_opcao(g)
        if chave in opcoes_vistas:
            avisos.append(
                f'Opção repetida preservada no grupo {g.grupo_id}: "{g.nome}" ({g.preco}).'
            )
        opcoes_vistas.add(chave)

    # Pizza sem método de preço definido não pode ir para o XLSX.
    # O xlsx_writer grava esse valor diretamente na aba Pizza; portanto 0
    # significa que ainda não há evidência segura para escolher a regra correta.
    for p in resultado.pizzas:
        metodo=int(getattr(p, "metodo_preco_pizza", 0) or 0)
        if metodo == 0:
            erros.append(
                f'Pizza "{p.nome}" está sem método de preço definido. '
                "Confira sabores/tamanhos antes de gerar o XLSX."
            )

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

    # Preços. Base zero só é pendência quando não existe preço estrutural comprovado
    # nos grupos vinculados. Isso evita falso alerta em pizzas como a Brendi, cujo
    # valor final é calculado pelos sabores (método de preço já definido).
    grupos_com_preco_positivo={
        str(g.grupo_id)
        for g in resultado.grupos
        if float(getattr(g, "preco", 0) or 0) > 0
    }
    for p in resultado.itens+resultado.pizzas:
        if p.preco < 0:
            erros.append(f'Preço negativo em "{p.nome}".')
        if p.preco == 0:
            gids={str(gid) for gid in (p.grupos or [])}
            preco_estruturado=bool(gids & grupos_com_preco_positivo)
            if not preco_estruturado:
                avisos.append(f'Preço zero em "{p.nome}".')

    if not resultado.itens and not resultado.pizzas:
        erros.append("Nenhum produto foi reconhecido.")

    return erros, avisos
