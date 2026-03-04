import streamlit as st
from supabase import create_client

# ---------------------------
# Configuração da página
# ---------------------------
st.set_page_config(
    page_title="RTP PRO – Avaliação Funcional",
    layout="wide"
)

st.title("🧠 RTP PRO – Avaliação Funcional")
st.write("Dr. Rodrigo Matos")

# ---------------------------
# Ler secrets do Streamlit
# ---------------------------
try:
    SUPABASE_URL = st.secrets["SUPABASE_URL"]
    SUPABASE_KEY = st.secrets["SUPABASE_SERVICE_ROLE"]

    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

except Exception as e:
    st.error(f"Erro ao conectar com Supabase: {e}")
    st.stop()

# ---------------------------
# Sidebar Paciente
# ---------------------------
st.sidebar.header("Paciente")
busca = st.sidebar.text_input("Buscar paciente (nome)")

# ---------------------------
# Ler pacientes
# ---------------------------
try:
    response = supabase.table("patients").select("*").execute()

    pacientes = response.data

    if busca:
        pacientes = [p for p in pacientes if busca.lower() in p["name"].lower()]

    for p in pacientes:
        st.sidebar.write(p["name"])

except Exception as e:
    st.error(f"Erro ao ler patients: {e}")
