import streamlit as st
from supabase import create_client
import pandas as pd
from datetime import datetime

st.set_page_config(page_title="RTP PRO – Avaliação Funcional", layout="wide")

SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_SERVICE_ROLE"]

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

st.title("🧠 RTP PRO – Avaliação Funcional")
st.subheader("Dr. Rodrigo Matos")

menu = st.sidebar.selectbox(
    "Menu",
    ["Cadastrar paciente", "Nova avaliação", "Histórico"]
)

if menu == "Cadastrar paciente":

    st.header("Cadastro de paciente")

    nome = st.text_input("Nome completo")
    nascimento = st.date_input("Data de nascimento")
    telefone = st.text_input("Telefone")
    email = st.text_input("Email")

    if st.button("Salvar paciente"):

        supabase.table("patients").insert({
            "full_name": nome,
            "birth_date": nascimento.isoformat(),
            "phone": telefone,
            "email": email
        }).execute()

        st.success("Paciente salvo")

if menu == "Nova avaliação":

    st.header("Nova avaliação")

    pacientes = supabase.table("patients").select("*").execute().data

    if pacientes:

        nomes = [p["full_name"] for p in pacientes]

        paciente_nome = st.selectbox("Paciente", nomes)

        paciente_id = next(p["id"] for p in pacientes if p["full_name"] == paciente_nome)

        dor = st.slider("Dor",0,10,5)
        mobilidade = st.slider("Mobilidade",0,10,5)
        forca = st.slider("Força",0,10,5)

        if st.button("Salvar avaliação"):

            risco = (dor*5) + ((10-mobilidade)*3) + ((10-forca)*3)

            supabase.table("assessments").insert({
                "patient_id": paciente_id,
                "assessment_type":"quick",
                "assessment_date": datetime.now().date().isoformat(),
                "pain_level": dor,
                "mobility": mobilidade,
                "strength": forca,
                "risk_score": risco
            }).execute()

            st.success("Avaliação salva")

            st.metric("Índice de risco", risco)

    else:

        st.warning("Cadastre um paciente primeiro")

if menu == "Histórico":

    st.header("Histórico de avaliações")

    pacientes = supabase.table("patients").select("*").execute().data

    if pacientes:

        nomes = [p["full_name"] for p in pacientes]

        paciente_nome = st.selectbox("Paciente", nomes)

        paciente_id = next(p["id"] for p in pacientes if p["full_name"] == paciente_nome)

        dados = supabase.table("assessments").select("*").eq("patient_id",paciente_id).execute().data

        if dados:

            df = pd.DataFrame(dados)

            st.dataframe(df)

            st.line_chart(df.set_index("assessment_date")[["pain_level","strength","risk_score"]])

        else:

            st.info("Sem avaliações")
