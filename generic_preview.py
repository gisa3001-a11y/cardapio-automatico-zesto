"""Previa generica do Leitor Universal V2.

Transforma estruturas JSON com evidencias fortes em uma previa normalizada.
Nao gera XLSX e nao substitui os parsers oficiais.

V2.3: inclui extracao conservadora de grupos/adicionais e evita que opcoes
internas (ex.: Bacon, Queijo) sejam promovidas a produtos principais.
"""

from dataclasses import dataclass, asdict
import hashlib
import re
from typing import Any, Dict, List, Optional, Tuple

from models import Produto, GrupoOpcao

NAME_KEYS = ("name", "nome", "title", "titulo", "product_name", "productname")
PRICE_KEYS = ("price", "preco", "preço", "value", "valor", "amount", "sale_price", "saleprice", "promotionalprice")
DESC_KEYS = ("description", "descricao", "descrição", "details", "detalhes")
IMAGE_KEYS = ("image", "imagem", "photo", "foto", "image_url", "imageurl", "coverimageurl", "src")
CATEGORY_KEYS = ("category", "categoria", "section", "secao", "seção", "category_name", "categoryname")
ID_KEYS = ("id", "product_id", "productid", "codigo", "code", "sku")
GROUP_KEYS = ("options", "optiongroups", "option_groups", "modifiers", "modifiergroups", "extras", "addons", "add_ons", "complements", "complementos", "choices", "variations")
OPTION_LIST_KEYS = ("items", "options", "choices", "values", "addons", "extras", "complements", "complementos", "modifiers")
MIN_KEYS = ("min", "minimum", "minimo", "mínimo", "min_selection", "minselect", "minimumquantity")
MAX_KEYS = ("max", "maximum", "maximo", "máximo", "max_selection", "maxselect", "maximumquantity", "limit")
REPEAT_KEYS = ("repeat", "repetir", "allow_repeat", "quantity_extras", "allowquantity")

NEGATIVE_KEY_HINTS = {
    "deliveryfee", "delivery_fee", "freight", "shipping", "shippingfee", "taxaentrega",
    "subtotal", "total", "totalprice", "cart", "carrinho", "checkout", "payment", "pagamento",
    "address", "endereco", "endereço", "zipcode", "cep", "latitude", "longitude", "distance",
    "merchant", "store", "restaurant", "establishment", "loja", "customer", "cliente", "user",
    "banner", "banners", "campaign", "campaigns", "coupon", "cupom", "discount", "desconto",
    "openinghours", "opening_hours", "schedule", "horario", "horário", "settings", "config",
}
NEGATIVE_NAME_RE = re.compile(
    r"^(?:taxa(?: de)? entrega|frete|subtotal|total|desconto|cupom|carrinho|checkout|"
    r"endereco|endereço|forma de pagamento|pagamento|troco|pedido minimo|pedido mínimo|"
    r"tempo de entrega|retirada|delivery|entrega)$", re.I,
)
ONLY_NUMBER_RE = re.compile(r"^[\d\s.,:/-]+$")


def _norm_key(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "")


def _lookup(obj: Dict[str, Any], keys) -> Any:
    mapa = {_norm_key(k): v for k, v in obj.items()}
    for key in keys:
        nk = _norm_key(key)
        if nk in mapa and mapa[nk] not in (None, "", [], {}):
            return mapa[nk]
    return None


def _texto(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (str, int, float)):
        return str(value).strip()
    if isinstance(value, dict):
        for key in NAME_KEYS:
            v = _lookup(value, (key,))
            if v not in (None, ""):
                return str(v).strip()
    return ""


def _preco(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        n = float(value)
        if isinstance(value, int) and n >= 1000:
            n = n / 100.0
        return round(n, 2)
    s = str(value).strip().replace("R$", "").replace(" ", "")
    if not s:
        return None
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return round(float(s), 2)
    except Exception:
        return None


def _inteiro(value: Any, padrao: int) -> int:
    try:
        return max(0, int(value))
    except Exception:
        return padrao


def _imagem(value: Any) -> str:
    if isinstance(value, str):
        v = value.strip()
        if v.startswith(("http://", "https://")):
            return v
    if isinstance(value, dict):
        for key in ("url", "src", "original", "large", "medium"):
            v = value.get(key)
            if isinstance(v, str) and v.startswith(("http://", "https://")):
                return v.strip()
    return ""


def _codigo(obj: Dict[str, Any], nome: str, preco: float) -> str:
    raw = _lookup(obj, ID_KEYS)
    if raw not in (None, ""):
        return str(raw).strip()
    base = f"{nome}|{preco:.2f}".encode("utf-8", "ignore")
    return "U-" + hashlib.sha1(base).hexdigest()[:12]


def _nome_parece_produto(nome: str) -> bool:
    n = (nome or "").strip()
    return bool(2 <= len(n) <= 180 and not ONLY_NUMBER_RE.match(n) and not NEGATIVE_NAME_RE.match(n))


def _tem_hint_negativo(obj: Dict[str, Any], path: str = "") -> bool:
    keys = {_norm_key(k) for k in obj.keys()}
    if keys & NEGATIVE_KEY_HINTS:
        fortes = bool(keys & {_norm_key(k) for k in IMAGE_KEYS + GROUP_KEYS + CATEGORY_KEYS})
        if not fortes:
            return True
    caminho = _norm_key(path)
    return any(h in caminho for h in NEGATIVE_KEY_HINTS)


def _score_produto(obj: Dict[str, Any], path: str = "") -> Tuple[int, List[str]]:
    nome = _texto(_lookup(obj, NAME_KEYS))
    preco = _preco(_lookup(obj, PRICE_KEYS))
    sinais: List[str] = []
    if not nome or preco is None or not _nome_parece_produto(nome) or preco < 0 or preco > 5000:
        return 0, sinais
    if _tem_hint_negativo(obj, path):
        return 0, sinais
    score = 6
    sinais.extend(["nome", "preco"])
    if _imagem(_lookup(obj, IMAGE_KEYS)):
        score += 2; sinais.append("imagem")
    if _texto(_lookup(obj, CATEGORY_KEYS)):
        score += 2; sinais.append("categoria")
    if _lookup(obj, DESC_KEYS):
        score += 1; sinais.append("descricao")
    if _lookup(obj, GROUP_KEYS):
        score += 3; sinais.append("grupos")
    if _lookup(obj, ID_KEYS) not in (None, ""):
        score += 1; sinais.append("id")
    return score, sinais


GROUP_KEY_SET = {_norm_key(k) for k in GROUP_KEYS}


def _walk(
    value: Any,
    path: str = "$",
    out: Optional[List[Dict[str, Any]]] = None,
    limite: int = 400,
    dentro_de_grupo: bool = False,
):
    """Percorre o JSON sem promover opcoes de adicionais a produtos principais."""
    if out is None:
        out = []
    if len(out) >= limite:
        return out

    if isinstance(value, dict):
        if not dentro_de_grupo:
            score, sinais = _score_produto(value, path)
            if score >= 6:
                out.append({"path": path, "score": score, "sinais": sinais, "obj": value})

        for k, v in list(value.items())[:180]:
            nk = _norm_key(k)
            filho_em_grupo = dentro_de_grupo or nk in GROUP_KEY_SET
            _walk(v, f"{path}.{k}", out, limite, filho_em_grupo)
            if len(out) >= limite:
                break

    elif isinstance(value, list):
        for i, v in enumerate(value[:250]):
            _walk(v, f"{path}[{i}]", out, limite, dentro_de_grupo)
            if len(out) >= limite:
                break
    return out


def _assinatura_produto(nome: str, preco: float, imagem: str) -> Tuple[str, float, str]:
    return (nome.strip().lower(), round(preco, 2), (imagem or "").strip().lower())


def _tipo_grupo(nome: str) -> int:
    n = (nome or "").lower()
    if "sabor" in n: return 2
    if "borda" in n: return 3
    if "massa" in n: return 4
    return 1


def _extrair_lista_grupos(obj: Dict[str, Any]) -> List[Dict[str, Any]]:
    valor = _lookup(obj, GROUP_KEYS)
    if isinstance(valor, list):
        return [g for g in valor if isinstance(g, dict)]
    if isinstance(valor, dict):
        interna = _lookup(valor, GROUP_KEYS + OPTION_LIST_KEYS)
        if isinstance(interna, list) and all(isinstance(x, dict) for x in interna):
            if any(isinstance(_lookup(x, OPTION_LIST_KEYS), list) for x in interna):
                return interna
        return [valor]
    return []


def _extrair_opcoes_grupo(grupo: Dict[str, Any]) -> List[Dict[str, Any]]:
    valor = _lookup(grupo, OPTION_LIST_KEYS)
    if isinstance(valor, list):
        return [x for x in valor if isinstance(x, dict)]
    return []


def _extrair_grupos_produto(obj: Dict[str, Any], produto_codigo: str) -> Tuple[List[str], List[GrupoOpcao]]:
    ids: List[str] = []
    linhas: List[GrupoOpcao] = []
    for idx, grupo in enumerate(_extrair_lista_grupos(obj)):
        grupo_nome = _texto(_lookup(grupo, NAME_KEYS)) or f"Grupo {idx + 1}"
        opcoes = _extrair_opcoes_grupo(grupo)
        if not opcoes:
            continue
        raw_gid = _lookup(grupo, ID_KEYS)
        gid = str(raw_gid).strip() if raw_gid not in (None, "") else "UG-" + hashlib.sha1(f"{produto_codigo}|{grupo_nome}|{idx}".encode()).hexdigest()[:10]
        minimo = _inteiro(_lookup(grupo, MIN_KEYS), 0)
        maximo = _inteiro(_lookup(grupo, MAX_KEYS), 1)
        if maximo < minimo:
            maximo = minimo
        repetir_raw = _lookup(grupo, REPEAT_KEYS)
        repetir = 1 if str(repetir_raw).lower() in ("1", "true", "yes", "sim") else 0
        adicionou = False
        for opcao in opcoes:
            nome = _texto(_lookup(opcao, NAME_KEYS))
            if not nome or not _nome_parece_produto(nome):
                continue
            preco = _preco(_lookup(opcao, PRICE_KEYS))
            if preco is None:
                preco = 0.0
            if preco < 0 or preco > 5000:
                continue
            linhas.append(GrupoOpcao(
                grupo_id=gid,
                tipo=_tipo_grupo(grupo_nome),
                grupo_nome=grupo_nome,
                nome=nome,
                imagem=_imagem(_lookup(opcao, IMAGE_KEYS)),
                preco=preco,
                minimo=minimo,
                maximo=maximo,
                repetir=repetir,
                metodo_preco=1,
            ))
            adicionou = True
        if adicionou:
            ids.append(gid)
    return ids, linhas


@dataclass
class PreviaGenerica:
    produtos: List[Produto]
    grupos: List[GrupoOpcao]
    confianca: str
    total_candidatos: int
    descartados_duplicados: int
    descartados_falsos_positivos: int
    avisos: List[str]

    def to_dict(self):
        return {
            "produtos": [asdict(p) for p in self.produtos],
            "grupos": [asdict(g) for g in self.grupos],
            "confianca": self.confianca,
            "total_candidatos": self.total_candidatos,
            "descartados_duplicados": self.descartados_duplicados,
            "descartados_falsos_positivos": self.descartados_falsos_positivos,
            "avisos": list(self.avisos),
            "pode_gerar_xlsx": False,
        }


def gerar_previa_de_payload(payload: Any, limite_produtos: int = 250) -> PreviaGenerica:
    candidatos = sorted(_walk(payload), key=lambda x: x["score"], reverse=True)
    produtos: List[Produto] = []
    grupos: List[GrupoOpcao] = []
    vistos = set(); grupos_vistos = set(); duplicados = 0; falsos = 0

    for c in candidatos:
        obj = c["obj"]
        nome = _texto(_lookup(obj, NAME_KEYS))
        preco = _preco(_lookup(obj, PRICE_KEYS))
        if not nome or preco is None or preco < 0 or not _nome_parece_produto(nome):
            falsos += 1; continue
        imagem = _imagem(_lookup(obj, IMAGE_KEYS))
        categoria = _texto(_lookup(obj, CATEGORY_KEYS))
        descricao = _texto(_lookup(obj, DESC_KEYS))
        codigo = _codigo(obj, nome, preco)
        chave = _assinatura_produto(nome, preco, imagem)
        if chave in vistos:
            duplicados += 1; continue
        vistos.add(chave)
        grupo_ids, linhas_grupos = _extrair_grupos_produto(obj, codigo)
        for g in linhas_grupos:
            assinatura = (g.grupo_id, g.nome.lower(), round(g.preco, 2))
            if assinatura not in grupos_vistos:
                grupos_vistos.add(assinatura); grupos.append(g)
        produtos.append(Produto(
            codigo=codigo, nome=nome, descricao=descricao, categoria=categoria,
            imagem=imagem, preco=preco, grupos=grupo_ids,
        ))
        if len(produtos) >= limite_produtos: break

    com_imagem = sum(1 for p in produtos if p.imagem)
    com_categoria = sum(1 for p in produtos if p.categoria)
    nomes_unicos = len({p.nome.strip().lower() for p in produtos})
    com_grupos = sum(1 for p in produtos if p.grupos)
    if len(produtos) >= 8 and nomes_unicos >= 6 and (com_imagem >= 3 or com_categoria >= 3):
        confianca = "alta"
    elif len(produtos) >= 3 and nomes_unicos >= 3:
        confianca = "media"
    else:
        confianca = "baixa"

    avisos = ["Previa generica: validar os itens e adicionais antes de qualquer exportacao."]
    if produtos and com_imagem == 0:
        avisos.append("Nenhuma imagem confiavel foi identificada na estrutura candidata.")
    if com_grupos:
        avisos.append(f"Grupos/adicionais encontrados em {com_grupos} produto(s); revisar minimo/maximo e precos.")
    if falsos:
        avisos.append(f"{falsos} candidato(s) foram descartados por parecerem metadados/taxas/carrinho.")
    if duplicados:
        avisos.append(f"{duplicados} candidato(s) duplicado(s) foram removidos.")

    return PreviaGenerica(produtos, grupos, confianca, len(candidatos), duplicados, falsos, avisos)
