import streamlit as st
from supabase import create_client

st.set_page_config(page_title="RTP PRO – Avaliação Funcional", layout="centered")

st.title("🧠 RTP PRO – Avaliação Funcional")
st.write("Dr. Rodrigo Matos")

# carregar secrets
SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_SERVICE_ROLE = st.secrets["SUPABASE_SERVICE_ROLE"]

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE)

st.header("Cadastrar Paciente")

name = st.text_input("Nome do paciente")
phone = st.text_input("Telefone")

if st.button("Salvar paciente"):
    if name:
        supabase.table("patients").insert(
            {"full_name": name, "phone": phone}
        ).execute()
        st.success("Paciente salvo!")

st.header("Nova Avaliação")

patient_name = st.text_input("Paciente")
score = st.number_input("Pontuação", min_value=0, max_value=100)

if st.button("Salvar avaliação"):
    if patient_name:
        patient = supabase.table("patients").select("*").eq("full_name", patient_name).execute()

        if patient.data:
            patient_id = patient.data[0]["id"]

            supabase.table("assessments").insert(
                {
                    "patient_id": patient_id,
                    "assessment_type": "RTP",
                    "assessment_date": "2026-01-01",
                    "score": score,
                }
            ).execute()

            st.success("Avaliação salva!")
