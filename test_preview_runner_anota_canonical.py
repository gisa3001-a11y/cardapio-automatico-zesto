from models import GrupoOpcao, Produto, Resultado
import preview_runner


def test_anota_prefere_parser_canonico_e_nao_promove_opcoes(monkeypatch):
    resultado = Resultado(
        itens=[
            Produto(
                codigo="suco-1",
                nome="Suco natural",
                categoria="Sucos",
                preco=12.0,
                grupos=["sabores-1"],
            )
        ],
        pizzas=[],
        grupos=[
            GrupoOpcao(
                grupo_id="sabores-1",
                tipo=1,
                grupo_nome="Escolha o sabor",
                nome="Laranja",
                preco=0.0,
                minimo=1,
                maximo=1,
                repetir=0,
                metodo_preco=1,
            ),
            GrupoOpcao(
                grupo_id="sabores-1",
                tipo=1,
                grupo_nome="Escolha o sabor",
                nome="Limao",
                preco=0.0,
                minimo=1,
                maximo=1,
                repetir=0,
                metodo_preco=1,
            ),
        ],
        origem="Anota AI teste",
    )

    import fetchers
    monkeypatch.setattr(fetchers, "buscar_anota_ai", lambda url: resultado)

    def nao_deveria_ir_ao_http(*args, **kwargs):
        raise AssertionError("O fluxo generico HTTP nao deveria rodar antes do parser canonico Anota AI")

    monkeypatch.setattr(preview_runner.requests, "get", nao_deveria_ir_ao_http)

    previa = preview_runner.gerar_previa_universal(
        "https://pedido.anota.ai/loja/bar-do-peixe-sta-1",
        permitir_browser=False,
    )

    nomes = [p["nome"] for p in previa.produtos]
    assert nomes == ["Suco natural"]
    assert "Laranja" not in nomes
    assert "Limao" not in nomes
    assert previa.fonte == "anota-ai:parser-canonico"
    assert previa.validacao["aprovado"] is False  # um item apenas: guardrail continua ativo
    assert any("menu_aux" in aviso for aviso in previa.avisos)


def test_anota_canonico_resolve_preco_zero_por_grupo_estruturado(monkeypatch):
    resultado = Resultado(
        itens=[
            Produto(
                codigo="acai-1",
                nome="Acai 500ml",
                categoria="Acai",
                preco=0.0,
                grupos=["tamanho-1"],
            ),
            Produto(codigo="agua-1", nome="Agua", categoria="Bebidas", preco=5.0),
            Produto(codigo="refri-1", nome="Refrigerante", categoria="Bebidas", preco=7.0),
        ],
        grupos=[
            GrupoOpcao(
                grupo_id="tamanho-1",
                tipo=1,
                grupo_nome="Tamanho",
                nome="500 ml",
                preco=18.0,
                minimo=1,
                maximo=1,
                repetir=0,
                metodo_preco=1,
            )
        ],
        origem="Anota AI teste",
    )

    import fetchers
    monkeypatch.setattr(fetchers, "buscar_anota_ai", lambda url: resultado)

    previa = preview_runner.gerar_previa_universal(
        "https://pedido.anota.ai/loja/teste",
        permitir_browser=False,
    )

    por_codigo = {p["codigo"]: p for p in previa.produtos}
    assert por_codigo["acai-1"]["preco"] == 18.0
    assert previa.validacao["metricas"]["precos_zero_pendentes"] == 0
    assert all(not str(p["codigo"]).startswith("U-") for p in previa.produtos)
