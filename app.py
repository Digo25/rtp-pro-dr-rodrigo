import streamlit as st

# ===== CONFIG =====
st.set_page_config(
    page_title="RTP PRO – Avaliação Funcional",
    layout="wide"
)

# ===== CABEÇALHO =====
st.title("🧠 RTP PRO – Avaliação Funcional")
st.subheader("Dr. Rodrigo Matos")
st.markdown("---")

# ===== MENU =====
menu = st.sidebar.selectbox(
    "Escolha a avaliação",
    ["⚡ Avaliação Rápida", "📋 Avaliação Completa"]
)

# ===== AVALIAÇÃO RÁPIDA =====
if menu == "⚡ Avaliação Rápida":

    st.header("⚡ Avaliação Rápida")

    nome = st.text_input("Nome do paciente")
    dor = st.slider("Nível de dor", 0, 10, 5)
    forca = st.slider("Força muscular (0-10)", 0, 10, 5)
    obs = st.text_area("Observações")

    if st.button("💾 Salvar avaliação"):
        st.success("Avaliação salva com sucesso!")

# ===== AVALIAÇÃO COMPLETA =====
if menu == "📋 Avaliação Completa":

    st.header("📋 Avaliação Completa")

    nome = st.text_input("Nome do paciente")
    idade = st.number_input("Idade", 0, 120, 30)
    patologia = st.text_input("Patologia principal")
    dor = st.slider("Nível de dor", 0, 10, 5)
    mobilidade = st.slider("Mobilidade", 0, 10, 5)
    forca = st.slider("Força muscular", 0, 10, 5)
    obs = st.text_area("Observações clínicas")

    if st.button("💾 Salvar avaliação completa"):
        st.success("Avaliação completa salva!")
