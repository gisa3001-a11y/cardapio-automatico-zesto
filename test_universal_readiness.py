from universal_readiness import avaliar_readiness, classificar_caso_sem_produtos


def test_404_nao_vira_falha_do_parser():
    r={"caso":"Ola Click","plataforma_detectada":"Ola Click","produtos":0,"avisos":[]}
    net={"dom":{"title":"Error 404","money_mentions":0,"product_word_mentions":1},"requests":[{"resource_type":"document","status":404,"path":"/products"}]}
    classe, _, bloqueia=classificar_caso_sem_produtos(r,net)
    assert classe == "url-indisponivel"
    assert bloqueia is False


def test_cloudflare_403_nao_vira_falha_do_parser():
    r={"caso":"MenuDino","plataforma_detectada":"MenuDino","produtos":0,"avisos":[]}
    net={"dom":{"title":"Attention Required! | Cloudflare","money_mentions":0,"product_word_mentions":1},"requests":[{"resource_type":"document","status":403,"path":"/"}]}
    classe, _, bloqueia=classificar_caso_sem_produtos(r,net)
    assert classe == "bloqueado-pelo-ambiente"
    assert bloqueia is False


def test_evidencia_de_catalogo_com_zero_bloqueia():
    r={"caso":"Exemplo","plataforma_detectada":"Exemplo","produtos":0,"avisos":[]}
    net={"dom":{"title":"Loja","money_mentions":12,"product_word_mentions":5},"requests":[{"resource_type":"document","status":200,"path":"/"}]}
    classe, _, bloqueia=classificar_caso_sem_produtos(r,net)
    assert classe == "falha-leitor-confirmada"
    assert bloqueia is True


def test_store_publico_vazio_nao_vira_falha_do_parser():
    r={"caso":"Saipos","plataforma_detectada":"Saipos","produtos":0,"avisos":[]}
    net={"dom":{"title":"Faca o seu pedido!","money_mentions":3,"product_word_mentions":1},"requests":[{"resource_type":"document","status":200,"path":"/"}]}
    probe={"respostas":[{"fonte":"browser:https://delivery-api.saipos.com/v1/stores?filter=x","schema":{"tipo":"list","tamanho":0}}]}
    classe, _, bloqueia=classificar_caso_sem_produtos(r,net,probe)
    assert classe == "fonte-publica-sem-loja"
    assert bloqueia is False


def test_valores_so_do_carrinho_nao_contam_como_catalogo():
    r={"caso":"Saipos","plataforma_detectada":"Saipos","produtos":0,"avisos":[]}
    net={
        "dom":{
            "title":"Faca o seu pedido!",
            "money_mentions":3,
            "product_word_mentions":1,
            "money_structure":[
                [{"tag":"h6","cls":["light-total"]},{"tag":"div","cls":["subtotal"]}],
                [{"tag":"h6","cls":["light-total"]},{"tag":"div","cls":["delivery"]}],
                [{"tag":"h6","cls":["dark-total"]},{"tag":"div","cls":["total"]}],
            ],
        },
        "requests":[{"resource_type":"document","status":200,"path":"/"}],
    }
    classe, _, bloqueia=classificar_caso_sem_produtos(r,net)
    assert classe == "interface-sem-catalogo-detectavel"
    assert bloqueia is False


def test_readiness_mantem_percentuais_brutos_e_pode_ficar_elegivel():
    resultados=[]
    for i in range(16):
        resultados.append({"caso":f"OK{i}","produtos":10,"validacao_aprovada":i < 14})
    resultados += [
        {"caso":"Ola Click","plataforma_detectada":"Ola Click","produtos":0,"avisos":[]},
        {"caso":"MenuDino","plataforma_detectada":"MenuDino","produtos":0,"avisos":[]},
        {"caso":"Atlas Automacao","plataforma_detectada":"Atlas Automacao","produtos":0,"avisos":[]},
        {"caso":"Saipos","plataforma_detectada":"Saipos","produtos":0,"avisos":[]},
    ]
    report={"total_casos":20,"com_produtos":16,"aprovados_validacao":14,"resultados":resultados}
    net=[
        {"caso":"Ola Click","dom":{"title":"Error 404","money_mentions":0,"product_word_mentions":1},"requests":[{"resource_type":"document","status":404,"path":"/products"}]},
        {"caso":"MenuDino","dom":{"title":"Attention Required! | Cloudflare","money_mentions":0,"product_word_mentions":1},"requests":[{"resource_type":"document","status":403,"path":"/"}]},
        {"caso":"Atlas Automacao","dom":{"title":"Loja","money_mentions":0,"product_word_mentions":0},"requests":[]},
        {"caso":"Saipos","dom":{"title":"Faca o seu pedido!","money_mentions":3,"product_word_mentions":1},"requests":[{"resource_type":"document","status":200,"path":"/"}]},
    ]
    probes=[
        {"caso":"Saipos","respostas":[{"fonte":"browser:https://delivery-api.saipos.com/v1/stores?filter=x","schema":{"tipo":"list","tamanho":0}}]}
    ]
    out=avaliar_readiness(report,net,probes)
    assert out["cobertura"] == 0.8
    assert out["taxa_aprovacao"] == 0.7
    assert out["pronto_para_considerar_merge"] is True
    assert out["merge_automatico"] is False
    assert len(out["casos_nao_testaveis_nesta_bateria"]) == 4
    assert out["falhas_confirmadas_do_leitor"] == []
