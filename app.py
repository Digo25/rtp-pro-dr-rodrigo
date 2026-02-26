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
        
        # ====== VERSÃO PROFISSIONAL ======

st.markdown("---")
st.header("📊 Resultado Profissional")

if st.button("📈 Gerar Resultado"):
    score = (10 - dor) + forca

    if score >= 15:
        resultado = "🟢 Excelente evolução funcional"
    elif score >= 10:
        resultado = "🟡 Evolução moderada — continuar tratamento"
    else:
        resultado = "🔴 Atenção — necessidade de intervenção intensiva"

    st.success(resultado)

    st.markdown("### 🧾 Resumo da Avaliação")
    st.write("Paciente:", nome)
    st.write("Dor:", dor)
    st.write("Força:", forca)
    st.write("Observações:", obs)