import re
import html as html_lib
from urllib.parse import urlparse

def texto_seguro(v):
    s = "" if v is None else str(v).strip()
    if s.startswith(("=", "+", "-", "@")):
        s = "\u200b" + s
    return s

def parse_preco(v):
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    s = re.sub(r"[^\d,.\-]", "", s)
    if not s:
        return 0.0
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except Exception:
        return 0.0

def imagem_compativel(url):
    if not url:
        return ""
    u = str(url).strip()
    low = u.lower().split("?")[0].split("#")[0]
    if low.endswith((".jpg", ".jpeg", ".png")):
        return u
    # Não mascara WEBP como JPG.
    if low.endswith(".webp"):
        return ""
    return u

def tipo_grupo(nome):
    n = (nome or "").lower()
    if re.search(r"\bsabor(?:es)?\b", n):
        return 2
    if re.search(r"\bborda(?:s)?\b", n):
        return 3
    if re.search(r"\bmassa(?:s)?\b", n):
        return 4
    return 1

def parece_combo(*partes):
    t = " ".join([str(x or "") for x in partes]).lower()
    return bool(re.search(r"\bcombo\b|kit|promo(?:ção|cao)|\+\s*\w+", t))

def parece_pizza(*partes):
    t = " ".join([str(x or "") for x in partes]).lower()
    if parece_combo(t):
        return False

    # Evidência direta e segura: nome/categoria/descrição menciona pizza/pizzaria.
    if re.search(r"\bpizza(?:s)?\b|\bpizzaria\b", t):
        return True

    # "meia" e "1/2" isolados aparecem em vários produtos que não são pizza.
    # Só servem como reforço quando existe também vocabulário típico de pizza.
    metade = bool(re.search(r"\b1/2\b|\bmeia\b", t))
    contexto_pizza = bool(re.search(r"\bsabor(?:es)?\b|\bborda(?:s)?\b|\bmassa(?:s)?\b|\btamanho(?:s)?\b", t))
    return metade and contexto_pizza

def slug_from_url(url):
    p = urlparse(url)
    parts = [x for x in p.path.split("/") if x]
    return parts[-1] if parts else ""
