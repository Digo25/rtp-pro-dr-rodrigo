import streamlit as st

st.set_page_config(page_title="RTP PRO - Dr Rodrigo", layout="wide")

st.title("RTP PRO - Avaliação Funcional")
st.subheader("Dr. Rodrigo Matos")

menu = st.sidebar.selectbox(
    "Escolha a avaliação",
    ["Avaliação Rápida", "Avaliação Completa"]
)

if menu == "Avaliação Rápida":
    st.header("Avaliação Rápida")
    nome = st.text_input("Nome do paciente")
    dor = st.slider("Nível de dor", 0, 10, 5)
    forca = st.slider("Força muscular (0-10)", 0, 10, 5)
    obs = st.text_area("Observações")

    if st.button("Salvar avaliação"):
        st.success("Avaliação salva com sucesso!")

if menu == "Avaliação Completa":
    st.header("Avaliação Completa")
    nome = st.text_input("Nome do paciente")
    idade = st.number_input("Idade", 0, 120, 30)
    dor = st.slider("Dor", 0, 10, 5)
    mobilidade = st.slider("Mobilidade", 0, 10, 5)
    forca = st.slider("Força", 0, 10, 5)
    potencia = st.slider("Potência muscular", 0, 10, 5)
    equilibrio = st.slider("Equilíbrio", 0, 10, 5)
    obs = st.text_area("Observações gerais")

    if st.button("Salvar avaliação completa"):
        st.success("Avaliação completa salva!")
