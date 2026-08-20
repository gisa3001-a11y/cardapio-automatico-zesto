# Cardápio Automático — Streamlit FINAL

Versão fechada para apresentação da alternativa **Python + Streamlit + Playwright**.

## Plataformas incluídas
Anota AI, RapidFood, byFood, InstaDelivery, Brendi, Ola Click, Saipos e Cardápio Web.

Foram retiradas da versão final: MenuDino, MeuComércio e Menui.

## Uso no VS Code

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m playwright install chromium
streamlit run app.py
```

O painel abre em `http://localhost:8501`.

## Publicação no Streamlit Community Cloud

Suba esta pasta para um repositório GitHub e crie um app apontando para `app.py`.
O arquivo `packages.txt` solicita Chromium no ambiente Linux do Streamlit Cloud; o código também procura automaticamente `/usr/bin/chromium`.

## Fluxo do usuário
1. Cola a URL do cardápio.
2. Envia o template oficial `.xlsx`.
3. Clica em **Ler cardápio e preparar prévia**.
4. Confere produtos, adicionais, categorias, fotos, pizzas e alertas.
5. Baixa o XLSX.

## Alertas da versão final
A interface avisa quando há produtos sem foto, nenhum vínculo de adicionais, preços zero ou inconsistências detectadas pelo validador. Diagnóstico técnico fica recolhido e não polui a apresentação.
