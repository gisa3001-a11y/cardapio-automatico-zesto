import json
from datetime import datetime

import pandas as pd
import streamlit as st

from fetchers import buscar_por_url, interpretar_html, diagnosticar_rede_universal, detectar_plataforma
from validator import validar
from xlsx_writer import gerar_xlsx

st.set_page_config(
    page_title="Cardápio Automático | Zesto",
    page_icon="🍽️",
    layout="wide",
    initial_sidebar_state="collapsed",
)

PLATAFORMAS_FINAIS = [
    "Anota AI", "RapidFood", "byFood", "InstaDelivery",
    "Brendi", "Ola Click", "Saipos", "Cardápio Web"
]

st.markdown(r"""
<style>
:root{
  --brand:#F26A3D; --brand2:#FF9A76; --ink:#2B211E; --muted:#786B66; --muted:#706B7B;
  --surface:#FFFFFF; --soft:#F7F5FB; --line:#E9E5F1; --ok:#137A4D; --warn:#A66500;
}
html, body, [class*="css"] {font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;}
.stApp{background:linear-gradient(180deg,#FFF9F6 0%,#FFF2EC 100%);}
.block-container{max-width:1180px;padding-top:1.6rem;padding-bottom:3rem;}
#MainMenu, footer, header{visibility:hidden;}
.hero{background:linear-gradient(135deg,#E9552F 0%,#F47752 58%,#FF9A76 100%);color:white;padding:34px 36px;border-radius:24px;box-shadow:0 18px 60px rgba(43,24,89,.18);margin-bottom:18px;}
.hero-kicker{font-size:.78rem;font-weight:800;letter-spacing:.11em;text-transform:uppercase;opacity:.78;margin-bottom:8px;}
.hero h1{font-size:2.15rem;line-height:1.08;margin:0 0 10px;font-weight:780;}
.hero p{font-size:1rem;max-width:760px;opacity:.86;margin:0;line-height:1.55;}
.pills{display:flex;gap:8px;flex-wrap:wrap;margin-top:18px}.pill{font-size:.77rem;padding:7px 10px;border-radius:99px;background:rgba(255,255,255,.12);border:1px solid rgba(255,255,255,.16)}
.section-title{font-size:1.13rem;font-weight:760;margin:26px 0 4px;color:var(--ink)}
.section-copy{color:var(--muted);font-size:.91rem;margin-bottom:14px}
[data-testid="stFileUploader"], [data-testid="stTextInputRootElement"], [data-testid="stTextArea"]{border-radius:14px;}
[data-testid="stMetric"]{background:var(--surface);border:1px solid var(--line);padding:16px 17px;border-radius:16px;box-shadow:0 5px 18px rgba(28,20,46,.035)}
[data-testid="stMetricLabel"]{font-size:.74rem;text-transform:uppercase;letter-spacing:.04em;color:var(--muted)}
[data-testid="stMetricValue"]{font-size:1.62rem;color:var(--ink);font-weight:760}
.stButton>button, .stDownloadButton>button{border-radius:12px;min-height:46px;font-weight:700;}
.stButton>button[kind="primary"], .stDownloadButton>button[kind="primary"]{background:linear-gradient(90deg,var(--brand),var(--brand2));border:none;}
.status-box{background:white;border:1px solid var(--line);border-radius:16px;padding:15px 17px;margin:10px 0 4px;}
.micro{font-size:.78rem;color:var(--muted)}
.platforms{background:white;border:1px solid var(--line);border-radius:16px;padding:15px 18px;color:var(--muted);font-size:.85rem;margin-top:12px;}
.platforms b{color:var(--ink)}
div[data-testid="stExpander"]{background:#fff;border:1px solid var(--line);border-radius:14px;}
[data-testid="stDataFrame"]{border:1px solid var(--line);border-radius:14px;overflow:hidden;}
</style>
""", unsafe_allow_html=True)

st.markdown("""
<div class="hero">
  <div class="hero-kicker">Zesto • Automação de cardápios</div>
  <h1>Cardápio Automático</h1>
  <p>Transforme um cardápio publicado em uma planilha XLSX pronta para importação, com leitura por navegador, conferência visual e alertas de consistência.</p>
  <div class="pills">
    <span class="pill">Reconhecimento automático</span><span class="pill">Playwright</span>
    <span class="pill">Pré-visualização</span><span class="pill">XLSX oficial</span>
  </div>
</div>
""", unsafe_allow_html=True)

with st.sidebar:
    st.markdown("### Cardápio Automático")
    st.caption("Versão final para apresentação")
    st.markdown("**Plataformas incluídas**")
    for p in PLATAFORMAS_FINAIS:
        st.write("✓", p)
    st.divider()
    st.caption("Retiradas da versão final: MenuDino, MeuComércio e Menui.")

st.markdown('<div class="section-title">1. Fonte de dados</div>', unsafe_allow_html=True)
st.markdown('<div class="section-copy">Use o link público do cardápio. A plataforma é identificada automaticamente.</div>', unsafe_allow_html=True)

c_url, c_mode = st.columns([3.2, 1], gap="medium")
with c_url:
    url = st.text_input("URL do cardápio", placeholder="https://...", label_visibility="collapsed")
with c_mode:
    modo = st.selectbox("Modo", ["URL automática", "HTML manual"], label_visibility="collapsed")

st.markdown(
    '<div class="platforms"><b>Plataformas finais:</b> ' + " • ".join(PLATAFORMAS_FINAIS) + '</div>',
    unsafe_allow_html=True,
)

html_manual = ""
if modo == "HTML manual":
    html_manual = st.text_area("HTML completo", height=220, placeholder="Cole o HTML da página aqui...")

st.markdown('<div class="section-title">2. Template oficial</div>', unsafe_allow_html=True)
st.markdown('<div class="section-copy">O arquivo mantém a estrutura oficial de importação. Nenhuma macro ou fórmula é adicionada.</div>', unsafe_allow_html=True)
template = st.file_uploader("Template oficial (.xlsx)", type=["xlsx"], label_visibility="collapsed")

acao1, acao2 = st.columns([1.5, 1], gap="medium")
with acao1:
    gerar = st.button("Ler cardápio e preparar prévia", type="primary", use_container_width=True)
with acao2:
    if st.button("Limpar resultado", use_container_width=True):
        for k in ("resultado", "diagnostico_rede", "resultado_url", "erro"):
            st.session_state.pop(k, None)
        st.rerun()

if gerar:
    for k in ("resultado", "diagnostico_rede", "resultado_url", "erro"):
        st.session_state.pop(k, None)
    try:
        if modo == "URL automática":
            if not url.strip():
                raise ValueError("Informe a URL do cardápio.")
            with st.spinner("Lendo produtos, categorias, preços, fotos e adicionais..."):
                resultado = buscar_por_url(url.strip(), usar_playwright=True)
            st.session_state["resultado_url"] = url.strip()
            diag = getattr(resultado, "_diagnostico_rede", None)
            if diag:
                st.session_state["diagnostico_rede"] = diag
        else:
            if not html_manual.strip():
                raise ValueError("Cole o HTML completo para continuar.")
            with st.spinner("Interpretando HTML..."):
                resultado = interpretar_html(html_manual, origem=url.strip() or "HTML manual")
            st.session_state["resultado_url"] = url.strip() or "HTML manual"
        st.session_state["resultado"] = resultado
    except Exception as exc:
        st.session_state["erro"] = str(exc)
        if modo == "URL automática" and url.strip():
            try:
                with st.spinner("Gerando diagnóstico técnico..."):
                    st.session_state["diagnostico_rede"] = diagnosticar_rede_universal(
                        url.strip(), plataforma=detectar_plataforma(url.strip()) or "Desconhecida"
                    )
            except Exception:
                pass

if st.session_state.get("erro"):
    st.error(st.session_state["erro"])

resultado = st.session_state.get("resultado")
if resultado:
    erros, avisos = validar(resultado)
    produtos = list(resultado.itens) + list(resultado.pizzas)
    total_produtos = len(produtos)
    com_foto = sum(bool(p.imagem) for p in produtos)
    sem_foto = total_produtos - com_foto
    com_grupo = sum(bool(p.grupos) for p in produtos)
    categorias = len(set(p.categoria for p in produtos if p.categoria))

    st.markdown('<div class="section-title">3. Conferência</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-copy">Confira o resumo antes de gerar o arquivo final.</div>', unsafe_allow_html=True)

    m1,m2,m3,m4,m5 = st.columns(5)
    m1.metric("Produtos", total_produtos)
    m2.metric("Adicionais", len(resultado.grupos))
    m3.metric("Categorias", categorias)
    m4.metric("Com foto", com_foto)
    m5.metric("Pizzas", len(resultado.pizzas))

    alertas = []
    if sem_foto:
        alertas.append(f"{sem_foto} produto(s) sem foto capturada")
    if total_produtos and com_grupo == 0:
        alertas.append("nenhum vínculo de adicionais foi encontrado")
    zeros = [p.nome for p in produtos if float(p.preco or 0) == 0]
    if zeros:
        alertas.append(f"{len(zeros)} produto(s) com preço zero — conferir se o valor é definido por sabores/opções")

    if erros:
        st.error("Há inconsistências que bloqueiam o XLSX.")
        with st.expander("Ver inconsistências", expanded=True):
            for x in erros:
                st.write("•", x)
    elif alertas or avisos:
        st.warning("A planilha pode ser gerada, mas há pontos que merecem conferência.")
        with st.expander("Avisos de conferência", expanded=False):
            for x in alertas:
                st.write("•", x)
            for x in avisos[:100]:
                st.write("•", x)
    else:
        st.success("Leitura concluída sem inconsistências bloqueantes.")

    rows=[]
    for p in resultado.itens:
        rows.append({"Tipo":"Regular","Categoria":p.categoria,"Produto":p.nome,"Preço":p.preco,
                     "Grupos":len(p.grupos or []),"Foto":"Sim" if p.imagem else "Não"})
    for p in resultado.pizzas:
        rows.append({"Tipo":"Pizza","Categoria":p.categoria,"Produto":p.nome,"Preço":p.preco,
                     "Grupos":len(p.grupos or []),"Foto":"Sim" if p.imagem else "Não"})
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True, height=390)

    if resultado.grupos:
        with st.expander(f"Adicionais capturados ({len(resultado.grupos)})"):
            grows=[{"ID":g.grupo_id,"Grupo":g.grupo_nome,"Opção":g.nome,"Preço":g.preco,
                    "Mín.":g.minimo,"Máx.":g.maximo} for g in resultado.grupos]
            st.dataframe(pd.DataFrame(grows), use_container_width=True, hide_index=True, height=320)

    with st.expander("Diagnóstico técnico", expanded=False):
        diag = st.session_state.get("diagnostico_rede")
        origem = getattr(resultado, "origem", "")
        st.caption(f"Fonte: {origem or 'parser da plataforma'}")
        st.caption(f"URL: {st.session_state.get('resultado_url','')}")
        if diag:
            rf = diag.get("resultado_final") or {}
            d1,d2,d3 = st.columns(3)
            d1.metric("Respostas de rede", diag.get("total_respostas_observadas",0))
            d2.metric("JSON candidatos", diag.get("total_json_candidatos",0))
            d3.metric("Vínculos", rf.get("vinculos_produto_grupo",0))
            diag_bytes=json.dumps(diag,ensure_ascii=False,indent=2,default=str).encode("utf-8")
            st.download_button("Baixar diagnóstico JSON",diag_bytes,"diagnostico_rede.json","application/json",use_container_width=True)

    st.markdown('<div class="section-title">4. Arquivo final</div>', unsafe_allow_html=True)
    if template and not erros:
        try:
            xlsx = gerar_xlsx(template.getvalue(), resultado)
            plataforma = detectar_plataforma(st.session_state.get("resultado_url", "")) or "cardapio"
            slug = re_safe = "".join(ch if ch.isalnum() else "_" for ch in plataforma.lower()).strip("_")
            nome = f"cardapio_{slug}_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.xlsx"
            st.download_button(
                "Baixar XLSX para importação",
                data=xlsx,
                file_name=nome,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
                type="primary",
            )
        except Exception as exc:
            st.error(f"Não foi possível preparar o XLSX: {exc}")
    elif not template:
        st.info("Envie o template oficial para liberar o download do XLSX.")

elif st.session_state.get("diagnostico_rede"):
    with st.expander("Diagnóstico técnico da tentativa", expanded=False):
        diag=st.session_state["diagnostico_rede"]
        st.json({
            "plataforma":diag.get("plataforma"),
            "respostas":diag.get("total_respostas_observadas",0),
            "json_candidatos":diag.get("total_json_candidatos",0),
            "erro":st.session_state.get("erro"),
        })

st.markdown("---")
st.caption("Cardápio Automático • versão final de apresentação • Python + Streamlit + Playwright")
