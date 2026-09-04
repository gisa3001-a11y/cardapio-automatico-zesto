"""Leitura isolada e testável da estrutura de pizzas da Brendi no __NUXT_DATA__.

Não altera o parser de produção. A função deste módulo é converter o estado
Nuxt público em uma estrutura estável de categorias, tamanhos e sabores com
preços por slug de tamanho. Depois de validado na bateria real, ele pode ser
ligado ao buscar_brendi sem duplicar regras heurísticas.
"""
from __future__ import annotations


def _resolve_ref(data, idx, depth=0, vistos=None):
    if vistos is None:
        vistos = set()
    if depth > 10:
        return None
    if not isinstance(idx, int) or not (0 <= idx < len(data)):
        return idx
    if idx in vistos:
        return None
    vistos = set(vistos)
    vistos.add(idx)
    value = data[idx]
    if not isinstance(value, (dict, list)):
        return value
    if isinstance(value, list):
        return [
            _resolve_ref(data, x, depth + 1, vistos) if isinstance(x, int) else x
            for x in value
        ]
    out = {}
    for k, v in value.items():
        if isinstance(v, int):
            out[str(k)] = _resolve_ref(data, v, depth + 1, vistos)
        elif isinstance(v, list):
            out[str(k)] = [
                _resolve_ref(data, x, depth + 1, vistos) if isinstance(x, int) else x
                for x in v
            ]
        else:
            out[str(k)] = v
    return out


def _campo(data, obj, nome, default=None):
    if not isinstance(obj, dict) or nome not in obj:
        return default
    v = obj.get(nome)
    if isinstance(v, int):
        return _resolve_ref(data, v)
    if isinstance(v, list):
        return [_resolve_ref(data, x) if isinstance(x, int) else x for x in v]
    return v


def extrair_pizzas_brendi_nuxt(data):
    """Retorna categorias, tamanhos e sabores de pizza do estado Nuxt Brendi.

    Cada sabor mantém ``prices`` resolvido; os registros observados em produção
    usam objetos como ``{"price": 5400, "slug": "grande-8-fatias"}``.
    O vínculo categoria -> sabores é feito pelo ID presente em ``categoryPath``.
    """
    if not isinstance(data, list):
        raise ValueError("Brendi: __NUXT_DATA__ inesperado; era esperada uma lista.")

    categories = []
    sizes = []
    flavors = []

    for obj in data:
        if not isinstance(obj, dict):
            continue
        keys = set(obj)
        name = _campo(data, obj, "name", "")
        main_category = _campo(data, obj, "mainCategory", "")
        category_path = _campo(data, obj, "categoryPath", "")

        if "productsPaths" in keys and str(main_category).lower() == "pizza":
            categories.append({
                "id": _campo(data, obj, "id"),
                "name": name,
                "calculateType": _campo(data, obj, "calculateType"),
                "productsPaths": _campo(data, obj, "productsPaths", []),
                "crusts": _campo(data, obj, "crusts", []),
                "edges": _campo(data, obj, "edges", []),
                "customs": _campo(data, obj, "customs", []),
                "customsPaths": _campo(data, obj, "customsPaths", []),
            })

        if "numOfFlavors" in keys and "slices" in keys:
            sizes.append({
                "id": _campo(data, obj, "id"),
                "name": name,
                "slug": _campo(data, obj, "slug"),
                "slices": _campo(data, obj, "slices"),
                "numOfFlavors": _campo(data, obj, "numOfFlavors", []),
            })

        if "prices" in keys and isinstance(category_path, str) and "/pizza-categories/" in category_path:
            flavors.append({
                "id": _campo(data, obj, "id"),
                "name": name,
                "slug": _campo(data, obj, "slug"),
                "active": _campo(data, obj, "active"),
                "categoryPath": category_path,
                "prices": _campo(data, obj, "prices", []),
                "pdvCodes": _campo(data, obj, "pdvCodes", []),
                "picture": _campo(data, obj, "picture", ""),
                "description": _campo(data, obj, "description", ""),
            })

    by_category = {}
    for flavor in flavors:
        path = str(flavor.get("categoryPath") or "")
        category_id = path.rsplit("/", 1)[-1] if "/" in path else ""
        if category_id:
            by_category.setdefault(category_id, []).append(flavor)

    return {
        "categories": categories,
        "sizes": sizes,
        "flavors": flavors,
        "flavorsByCategory": by_category,
    }
