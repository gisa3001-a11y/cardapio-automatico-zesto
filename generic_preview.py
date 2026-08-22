"""Previa generica do Leitor Universal V2.

Transforma apenas estruturas JSON com evidencias fortes em uma previa normalizada.
Nao gera XLSX e nao substitui os parsers oficiais.

V2.1: adiciona filtros contra falsos produtos (taxas, carrinho, endereco,
configuracoes, banners e metadados) e exige coerencia estrutural minima.
"""

from dataclasses import dataclass, asdict
import hashlib
import re
from typing import Any, Dict, List, Optional, Tuple

from models import Produto


NAME_KEYS = ("name", "nome", "title", "titulo", "product_name", "productname")
PRICE_KEYS = ("price", "preco", "preço", "value", "valor", "amount", "sale_price", "saleprice", "promotionalprice")
DESC_KEYS = ("description", "descricao", "descrição", "details", "detalhes")
IMAGE_KEYS = ("image", "imagem", "photo", "foto", "image_url", "imageurl", "coverimageurl", "src")
CATEGORY_KEYS = ("category", "categoria", "section", "secao", "seção", "category_name", "categoryname")
ID_KEYS = ("id", "product_id", "productid", "codigo", "code", "sku")
GROUP_KEYS = ("options", "optiongroups", "option_groups", "modifiers", "modifiergroups", "extras", "addons", "add_ons", "complements", "complementos", "choices", "variations")

# Chaves e nomes comuns que aparecem em payloads de delivery, mas nao representam produtos.
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
    r"tempo de entrega|retirada|delivery|entrega)$",
    re.I,
)

# Nomes muito curtos/numericos tendem a ser metadado e nao item real.
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
        # Algumas APIs armazenam centavos como inteiro.
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


def _tem_hint_negativo(obj: Dict[str, Any], path: str = "") -> bool:
    keys = {_norm_key(k) for k in obj.keys()}
    if keys & NEGATIVE_KEY_HINTS:
        # Nao descarta automaticamente se tambem houver sinais fortes de produto.
        fortes = bool(keys & {_norm_key(k) for k in IMAGE_KEYS + GROUP_KEYS + CATEGORY_KEYS})
        if not fortes:
            return True
    caminho = _norm_key(path)
    return any(h in caminho for h in NEGATIVE_KEY_HINTS)


def _nome_parece_produto(nome: str) -> bool:
    n = (nome or "").strip()
    if len(n) < 2 or len(n) > 180:
        return False
    if ONLY_NUMBER_RE.match(n):
        return False
    if NEGATIVE_NAME_RE.match(n):
        return False
    return True


def _score_produto(obj: Dict[str, Any], path: str = "") -> Tuple[int, List[str]]:
    nome = _texto(_lookup(obj, NAME_KEYS))
    preco = _preco(_lookup(obj, PRICE_KEYS))
    sinais: List[str] = []
    if not nome or preco is None or not _nome_parece_produto(nome):
        return 0, sinais
    if preco < 0 or preco > 5000:
        return 0, sinais
    if _tem_hint_negativo(obj, path):
        return 0, sinais

    score = 6
    sinais.extend(["nome", "preco"])
    if _imagem(_lookup(obj, IMAGE_KEYS)):
        score += 2
        sinais.append("imagem")
    if _texto(_lookup(obj, CATEGORY_KEYS)):
        score += 2
        sinais.append("categoria")
    if _lookup(obj, DESC_KEYS):
        score += 1
        sinais.append("descricao")
    if _lookup(obj, GROUP_KEYS):
        score += 3
        sinais.append("grupos")
    if _lookup(obj, ID_KEYS) not in (None, ""):
        score += 1
        sinais.append("id")
    return score, sinais


def _walk(value: Any, path: str = "$", out: Optional[List[Dict[str, Any]]] = None, limite: int = 400):
    if out is None:
        out = []
    if len(out) >= limite:
        return out
    if isinstance(value, dict):
        score, sinais = _score_produto(value, path)
        if score >= 6:
            out.append({"path": path, "score": score, "sinais": sinais, "obj": value})
        for k, v in list(value.items())[:180]:
            _walk(v, f"{path}.{k}", out, limite)
            if len(out) >= limite:
                break
    elif isinstance(value, list):
        for i, v in enumerate(value[:250]):
            _walk(v, f"{path}[{i}]", out, limite)
            if len(out) >= limite:
                break
    return out


def _assinatura_produto(obj: Dict[str, Any], nome: str, preco: float, imagem: str) -> Tuple[str, float, str]:
    # Deduplicacao propositalmente ignora IDs diferentes quando nome/preco/imagem sao iguais.
    return (nome.strip().lower(), round(preco, 2), (imagem or "").strip().lower())


@dataclass
class PreviaGenerica:
    produtos: List[Produto]
    confianca: str
    total_candidatos: int
    descartados_duplicados: int
    descartados_falsos_positivos: int
    avisos: List[str]

    def to_dict(self):
        return {
            "produtos": [asdict(p) for p in self.produtos],
            "confianca": self.confianca,
            "total_candidatos": self.total_candidatos,
            "descartados_duplicados": self.descartados_duplicados,
            "descartados_falsos_positivos": self.descartados_falsos_positivos,
            "avisos": list(self.avisos),
            "pode_gerar_xlsx": False,
        }


def gerar_previa_de_payload(payload: Any, limite_produtos: int = 250) -> PreviaGenerica:
    brutos = _walk(payload)
    candidatos = sorted(brutos, key=lambda x: x["score"], reverse=True)
    produtos: List[Produto] = []
    vistos = set()
    duplicados = 0
    falsos = 0

    for c in candidatos:
        obj = c["obj"]
        nome = _texto(_lookup(obj, NAME_KEYS))
        preco = _preco(_lookup(obj, PRICE_KEYS))
        if not nome or preco is None or preco < 0 or not _nome_parece_produto(nome):
            falsos += 1
            continue
        imagem = _imagem(_lookup(obj, IMAGE_KEYS))
        categoria = _texto(_lookup(obj, CATEGORY_KEYS))
        descricao = _texto(_lookup(obj, DESC_KEYS))
        codigo = _codigo(obj, nome, preco)
        chave = _assinatura_produto(obj, nome, preco, imagem)
        if chave in vistos:
            duplicados += 1
            continue
        vistos.add(chave)
        produtos.append(Produto(
            codigo=codigo,
            nome=nome,
            descricao=descricao,
            categoria=categoria,
            imagem=imagem,
            preco=preco,
        ))
        if len(produtos) >= limite_produtos:
            break

    com_imagem = sum(1 for p in produtos if p.imagem)
    com_categoria = sum(1 for p in produtos if p.categoria)
    nomes_unicos = len({p.nome.strip().lower() for p in produtos})

    # Alta confianca exige quantidade + diversidade + algum contexto estrutural.
    if len(produtos) >= 8 and nomes_unicos >= 6 and (com_imagem >= 3 or com_categoria >= 3):
        confianca = "alta"
    elif len(produtos) >= 3 and nomes_unicos >= 3:
        confianca = "media"
    else:
        confianca = "baixa"

    avisos = ["Previa generica: validar os itens antes de qualquer exportacao."]
    if produtos and com_imagem == 0:
        avisos.append("Nenhuma imagem confiavel foi identificada na estrutura candidata.")
    if falsos:
        avisos.append(f"{falsos} candidato(s) foram descartados por parecerem metadados/taxas/carrinho.")
    if duplicados:
        avisos.append(f"{duplicados} candidato(s) duplicado(s) foram removidos.")

    return PreviaGenerica(produtos, confianca, len(candidatos), duplicados, falsos, avisos)
