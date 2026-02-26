import streamlit as st

st.set_page_config(
    page_title="RTP PRO - Avaliação Funcional",
    layout="wide"
)

# ===== CABEÇALHO =====
st.title("🧠 RTP PRO - Avaliação Funcional")
st.subheader("Dr. Rodrigo Matos")

st.markdown("---")

# ===== MENU =====
menu = st.sidebar.selectbox(
    "Escolha a avaliação",
    ["Avaliação Rápida", "Avaliação Completa", "Comparação Evolutiva"]
)

# ===== AVALIAÇÃO RÁPIDA =====
if menu == "Avaliação Rápida":

    st.header("⚡ Avaliação Rápida")

    nome = st.text_input("Nome do paciente")
    dor = st.slider("Nível de dor", 0, 10, 5)
    forca = st.slider("Força muscular (0-10)", 0, 10, 5)
    mobilidade = st.slider("Mobilidade (0-10)", 0, 10, 5)
    obs = st.text_area("Observações")

    if st.button("💾 Salvar avaliação"):
        st.success("Avaliação salva com sucesso!")

# ===== AVALIAÇÃO COMPLETA =====
if menu == "Avaliação Completa":

    st.header("📋 Avaliação Completa")

    nome = st.text_input("Nome do paciente")
    idade = st.number_input("Idade", 0, 120)
    profissao = st.text_input("Profissão")

    st.subheader("Escalas clínicas")

    dor = st.slider("Dor", 0, 10, 5)
    forca = st.slider("Força", 0, 10, 5)
    equilibrio = st.slider("Equilíbrio", 0, 10, 5)
    funcional = st.slider("Funcionalidade", 0, 10, 5)

    diagnostico = st.text_area("Hipótese diagnóstica")
    plano = st.text_area("Plano terapêutico")

    if st.button("📊 Finalizar avaliação"):
        st.success("Avaliação completa salva!")

# ===== COMPARAÇÃO =====
if menu == "Comparação Evolutiva":

    st.header("📈 Comparação Evolutiva")

    st.info("Aqui você poderá comparar avaliações futuras do paciente.")

    st.metric("Dor inicial", "8")
    st.metric("Dor atual", "3")
