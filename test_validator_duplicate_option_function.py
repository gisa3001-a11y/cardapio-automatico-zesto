from models import GrupoOpcao, Produto, Resultado
from validator import validar


def _produto():
    return Produto(codigo="p1", nome="Produto", categoria="Bebidas", preco=10, grupos=["g1"])


def test_mesmo_nome_preco_com_funcao_diferente_nao_bloqueia():
    grupos = [
        GrupoOpcao(
            grupo_id="g1",
            tipo=1,
            grupo_nome="Sabores",
            nome="Goiaba Morango",
            preco=11,
            minimo=0,
            maximo=1,
            repetir=0,
            metodo_preco=1,
        ),
        GrupoOpcao(
            grupo_id="g1",
            tipo=1,
            grupo_nome="Sabores",
            nome="Goiaba Morango",
            preco=11,
            minimo=1,
            maximo=2,
            repetir=1,
            metodo_preco=1,
        ),
    ]
    resultado = Resultado(itens=[_produto()], grupos=grupos)

    erros, _ = validar(resultado)

    assert not any("Opção duplicada" in erro for erro in erros)
    assert len(resultado.grupos) == 2


def test_opcao_realmente_identica_continua_bloqueada():
    grupo = dict(
        grupo_id="g1",
        tipo=1,
        grupo_nome="Sabores",
        nome="Strawberry Ice",
        preco=11,
        minimo=0,
        maximo=1,
        repetir=0,
        metodo_preco=1,
    )
    resultado = Resultado(
        itens=[_produto()],
        grupos=[GrupoOpcao(**grupo), GrupoOpcao(**grupo)],
    )

    erros, _ = validar(resultado)

    assert any("Opção duplicada" in erro for erro in erros)
