"""Leitor Universal V2 — roteador isolado e seguro.

Nao substitui parsers atuais e nao libera XLSX para estruturas desconhecidas.
"""
import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


@dataclass(frozen=True)
class DeteccaoURL:
    url_original: str
    url_normalizada: str
    plataforma: Optional[str]
    metodo: str
    confianca: str
    estrategia: str
    motivo: str


DOMINIOS_CONHECIDOS = {
    "anota.ai": ("Anota AI", "playwright-prioritario"),
    "rapidfood.com.br": ("RapidFood", "direto"),
    "byfood.com.br": ("byFood", "direto"),
    "instadelivery.com.br": ("InstaDelivery", "direto"),
    "brendi.com.br": ("Brendi", "playwright-prioritario"),
    "whatsmenu.com.br": ("WhatsMenu", "playwright-prioritario"),
    "ola.click": ("Ola Click", "playwright-prioritario"),
    "cardapioweb.com": ("Cardapio Web", "direto"),
    "saipos.com": ("Saipos", "playwright-prioritario"),
    "menudino.com": ("MenuDino", "direto"),
    "menuintegrado.com.br": ("Menui / Menu Integrado", "playwright-prioritario"),
    "menui.com.br": ("Menui / Menu Integrado", "playwright-prioritario"),
    "meucomercio.com.br": ("MeuComercio", "direto"),
    "atlasautomacao.app.br": ("Atlas Automacao", "diagnostico"),
    "hubt.com.br": ("Hubt", "diagnostico"),
    "theozburger.com.br": ("Yooga Delivery", "diagnostico"),
    "neemo.com.br": ("Neemo", "diagnostico"),
    "entregueja.com.br": ("EntregueJa", "diagnostico"),
    "ecta.com.br": ("ECTA", "diagnostico"),
    "pedidosite.com.br": ("PedidoSite", "diagnostico"),
    "bigd.im": ("BigD", "diagnostico"),
    "my.canva.site": ("Canva Site", "diagnostico"),
    "chefjuliaandrade.com.br": ("Dominio proprio", "diagnostico"),
    "loja.menu": ("Loja.Menu", "diagnostico"),
    "lapizzaiola.com.br": ("Dominio proprio", "diagnostico"),
}

PARAMETROS_RASTREAMENTO = {"fbclid", "gclid", "dclid", "msclkid", "mc_cid", "mc_eid"}
HOSTS_NAO_CARDAPIO = {"chat.whatsapp.com", "wa.me", "api.whatsapp.com"}


def _limpar_query(query: str) -> str:
    pares = []
    for chave, valor in parse_qsl(query or "", keep_blank_values=True):
        c = chave.lower()
        if c in PARAMETROS_RASTREAMENTO or c.startswith("utm_"):
            continue
        pares.append((chave, valor))
    return urlencode(pares, doseq=True)


def normalizar_url(url: str) -> str:
    valor = (url or "").strip()
    if not valor:
        raise ValueError("Informe a URL do cardapio.")
    if "://" not in valor:
        valor = "https://" + valor
    p = urlparse(valor)
    if p.scheme.lower() not in ("http", "https") or not p.netloc:
        raise ValueError("URL de cardapio invalida.")
    host = (p.hostname or "").lower().strip(".")
    if not host:
        raise ValueError("URL de cardapio invalida.")
    if host in HOSTS_NAO_CARDAPIO or host.endswith(".whatsapp.com"):
        raise ValueError("Este link nao e um cardapio publico; parece ser um link do WhatsApp.")
    porta = f":{p.port}" if p.port else ""
    return urlunparse((p.scheme.lower(), host + porta, p.path or "/", "", _limpar_query(p.query), ""))


def _dominio_corresponde(host: str, base: str) -> bool:
    return host == base or host.endswith("." + base)


def _detectar_por_dominio(url: str):
    host = (urlparse(url).hostname or "").lower()
    for base, (plataforma, estrategia) in DOMINIOS_CONHECIDOS.items():
        if _dominio_corresponde(host, base):
            return plataforma, estrategia, base
    return None, None, None


def _host_contem_nome_de_dominio_sem_corresponder(host: str) -> bool:
    """Bloqueia falso positivo como brendi.com.br.exemplo.com.

    O detector legado pode procurar substrings no URL inteiro. Se o host contem o
    texto de um dominio conhecido, mas nao e esse dominio nem subdominio dele,
    nao delegamos ao detector legado.
    """
    return any(base in host and not _dominio_corresponde(host, base) for base in DOMINIOS_CONHECIDOS)


def detectar_url(url: str) -> DeteccaoURL:
    normalizada = normalizar_url(url)
    plataforma, estrategia, base = _detectar_por_dominio(normalizada)
    if plataforma:
        return DeteccaoURL(
            url, normalizada, plataforma, "dominio",
            "alta" if estrategia != "diagnostico" else "dominio-confirmado",
            estrategia, f"Dominio reconhecido: {base}"
        )

    host = (urlparse(normalizada).hostname or "").lower()
    if not _host_contem_nome_de_dominio_sem_corresponder(host):
        from fetchers import detectar_plataforma
        existente = detectar_plataforma(normalizada)
        if existente:
            return DeteccaoURL(
                url, normalizada, existente, "detector-existente", "alta", "auto",
                "Reconhecido pelo detector atual do projeto"
            )

    return DeteccaoURL(
        url, normalizada, None, "fallback-universal", "a-confirmar", "diagnostico",
        "Dominio ainda nao cadastrado; encaminhar para diagnostico universal"
    )


def diagnosticar_url_universal(url: str):
    """Analisa sinais estruturais; nao gera XLSX."""
    deteccao = detectar_url(url)
    from structure_detector import diagnosticar_estrutura
    return deteccao, diagnosticar_estrutura(deteccao.url_normalizada)


def gerar_previa_url_universal(url: str):
    """Tenta montar previa de produtos; XLSX continua bloqueado."""
    deteccao = detectar_url(url)
    from preview_runner import gerar_previa_universal
    previa = gerar_previa_universal(deteccao.url_normalizada)
    return deteccao, previa


def _sanear_classificacao_anota(resultado, plataforma: Optional[str]):
    """Corrige somente o falso positivo real comprovado de vinho como pizza.

    O payload atual do Anota AI pode marcar uma categoria com ``category_type``
    igual a ``pizza`` mesmo quando os produtos nela sao vinhos. O parser legado
    preserva esse campo como pista forte e, por isso, esses produtos acabam na
    lista de pizzas. No Universal V2 fazemos uma correcao conservadora: um item
    explicitamente identificado como vinho so permanece pizza quando o proprio
    nome traz evidencia semantica de pizza.

    Categoria e descricao nao entram nessa segunda checagem porque ambos podem
    herdar contexto contaminado da categoria incorreta comprovada no caso real.
    Uma pizza genuina que mencione vinho continua protegida quando o nome traz
    evidencia explicita de pizza, como "Pizza com Vinho".

    A regra fica restrita ao Anota AI e ao caso comprovado; nenhuma classificacao
    das demais plataformas e alterada.
    """
    if plataforma != "Anota AI" or resultado is None or not getattr(resultado, "pizzas", None):
        return resultado

    from utils import parece_pizza

    manter = []
    regulares = []
    for produto in list(resultado.pizzas or []):
        nome = str(getattr(produto, "nome", "") or "")
        texto = f"{nome} {getattr(produto, 'categoria', '')}"
        eh_vinho = bool(re.search(r"\bvinho(?:s)?\b", texto, re.IGNORECASE))
        tem_evidencia_pizza = parece_pizza(nome, "", "")
        if eh_vinho and not tem_evidencia_pizza:
            produto.pizza = False
            produto.metodo_preco_pizza = 0
            regulares.append(produto)
        else:
            manter.append(produto)

    if regulares:
        resultado.pizzas = manter
        resultado.itens.extend(regulares)
        nomes = ", ".join(str(getattr(p, "nome", "")) for p in regulares[:6])
        resultado.avisos.append(
            f"Universal V2 reclassificou {len(regulares)} vinho(s) que o Anota AI marcou como pizza sem evidencia semantica no nome: {nomes}."
        )

    return resultado


def _sanear_classificacao_olaclick(resultado, plataforma: Optional[str]):
    """Corrige somente o falso positivo comprovado de pastel como pizza no Ola Click.

    No cardapio real validado, o produto "Pastel" aparece em uma categoria de
    cafe da manha e sua descricao enumera sabores, incluindo a palavra "pizza".
    O classificador generico usa nome/categoria/descricao e, por isso, marcava o
    pastel inteiro como pizza. Para evitar alterar pizzas verdadeiras, a correcao
    fica restrita ao Ola Click e a produtos identificados como pastel: eles so
    saem de pizzas quando nome e categoria, sem a descricao, nao trazem evidencia
    semantica de pizza. Assim, "Pastel de Pizza" ou pastel dentro de categoria
    explicitamente de pizzas continua preservado.
    """
    if plataforma != "Ola Click" or resultado is None or not getattr(resultado, "pizzas", None):
        return resultado

    from utils import parece_pizza

    manter = []
    regulares = []
    for produto in list(resultado.pizzas or []):
        nome = str(getattr(produto, "nome", "") or "")
        categoria = str(getattr(produto, "categoria", "") or "")
        eh_pastel = bool(re.search(r"\bpast(?:el|eis)\b", nome, re.IGNORECASE))
        tem_evidencia_pizza_nome_categoria = parece_pizza(nome, categoria, "")
        if eh_pastel and not tem_evidencia_pizza_nome_categoria:
            produto.pizza = False
            produto.metodo_preco_pizza = 0
            regulares.append(produto)
        else:
            manter.append(produto)

    if regulares:
        resultado.pizzas = manter
        resultado.itens.extend(regulares)
        nomes = ", ".join(str(getattr(p, "nome", "")) for p in regulares[:6])
        resultado.avisos.append(
            f"Universal V2 reclassificou {len(regulares)} pastel(is) que o Ola Click marcou como pizza apenas pelo texto descritivo: {nomes}."
        )

    return resultado


def ler_url_universal(url: str, usar_playwright: bool = True):
    deteccao = detectar_url(url)
    if deteccao.estrategia == "diagnostico":
        return None, deteccao

    from fetchers import buscar_por_url
    resultado = buscar_por_url(deteccao.url_normalizada, usar_playwright=bool(usar_playwright))
    resultado = _sanear_classificacao_anota(resultado, deteccao.plataforma)
    resultado = _sanear_classificacao_olaclick(resultado, deteccao.plataforma)
    try:
        setattr(resultado, "_leitor_universal", {
            "plataforma": deteccao.plataforma,
            "metodo": deteccao.metodo,
            "confianca": deteccao.confianca,
            "estrategia": deteccao.estrategia,
            "motivo": deteccao.motivo,
            "url_normalizada": deteccao.url_normalizada,
        })
    except Exception:
        pass
    return resultado, deteccao
