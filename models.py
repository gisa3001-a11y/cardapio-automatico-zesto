from dataclasses import dataclass, field
from typing import List

@dataclass
class GrupoOpcao:
    grupo_id: str
    tipo: int
    grupo_nome: str
    nome: str
    imagem: str = ""
    preco: float = 0.0
    minimo: int = 0
    maximo: int = 1
    repetir: int = 0
    metodo_preco: int = 1

@dataclass
class Produto:
    codigo: str
    nome: str
    descricao: str = ""
    categoria: str = ""
    imagem: str = ""
    preco: float = 0.0
    grupos: List[str] = field(default_factory=list)
    pizza: bool = False
    combo: bool = False
    metodo_preco_pizza: int = 0

@dataclass
class Resultado:
    itens: List[Produto] = field(default_factory=list)
    pizzas: List[Produto] = field(default_factory=list)
    grupos: List[GrupoOpcao] = field(default_factory=list)
    origem: str = ""
    avisos: List[str] = field(default_factory=list)
