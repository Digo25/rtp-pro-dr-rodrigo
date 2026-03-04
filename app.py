import os
from datetime import datetime, date
from io import BytesIO

import streamlit as st
import pandas as pd

# Supabase (Python client)
from supabase import create_client

# PDF (reportlab)
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas


# -----------------------------
# Configuração da página
# -----------------------------
st.set_page_config(
    page_title="RTP PRO - Avaliação Funcional",
    layout="wide",
)


# -----------------------------
# Helpers: Secrets / Env
# -----------------------------
def get_secret(key: str, default: str = "") -> str:
    # Streamlit Cloud: st.secrets; Local: env
    if "secrets" in dir(st) and key in st.secrets:
        return str(st.secrets.get(key, default)).strip()
    return str(os.getenv(key, default)).strip()


def supabase_client():
    url = get_secret("SUPABASE_URL")
    key = get_secret("SUPABASE_SERVICE_ROLE")

    # Validações bem explícitas
    if not url:
        raise RuntimeError("SUPABASE_URL não definido no Secrets.")
    if not key:
        raise RuntimeError("SUPABASE_SERVICE_ROLE não definido no Secrets.")

    # Erro comum: URL quebrada/truncada (.co ao invés de .com)
    if "supabase.co" not in url or url.endswith("supabase.co") is False:
        # ainda assim pode ser válido, mas aqui ajudamos a detectar
        pass

    return create_client(url, key)


# -----------------------------
# Banco: criar tabelas (SQL)
# (Você executa isso no Supabase SQL Editor)
# -----------------------------
SQL_TABLES = """\
-- 1) patients
create table if not exists patients (
  id uuid primary key default gen_random_uuid(),
  full_name text not null,
  phone text,
  created_at timestamptz not null default now()
);

-- 2) assessments
create table if not exists assessments (
  id uuid primary key default gen_random_uuid(),
  patient_id uuid not null references patients(id) on delete cascade,
  assessment_type text not null,
  assessment_date date not null,
  score int not null,
  notes text,
  created_at timestamptz not null default now()
);
"""


# -----------------------------
# PDF
# -----------------------------
def make_patient_pdf(patient_name: str, patient_phone: str, assessments: pd.DataFrame) -> bytes:
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    y = height - 50
    c.setFont("Helvetica-Bold", 16)
    c.drawString(50, y, "RTP PRO - Relatório do Paciente")
    y -= 30

    c.setFont("Helvetica", 12)
    c.drawString(50, y, f"Paciente: {patient_name}")
    y -= 18
    c.drawString(50, y, f"Telefone: {patient_phone or '-'}")
    y -= 18
    c.drawString(50, y, f"Gerado em: {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    y -= 30

    c.setFont("Helvetica-Bold", 12)
    c.drawString(50, y, "Avaliações:")
    y -= 18

    c.setFont("Helvetica", 10)

    if assessments.empty:
        c.drawString(50, y, "Nenhuma avaliação registrada.")
    else:
        # Cabeçalho
        c.setFont("Helvetica-Bold", 10)
        c.drawString(50, y, "Data")
        c.drawString(120, y, "Tipo")
        c.drawString(320, y, "Score")
        c.drawString(380, y, "Notas")
        y -= 14
        c.setFont("Helvetica", 10)

        for _, row in assessments.iterrows():
            if y < 80:
                c.showPage()
                y = height - 50
                c.setFont("Helvetica", 10)

            c.drawString(50, y, str(row.get("assessment_date", "")))
            c.drawString(120, y, str(row.get("assessment_type", ""))[:28])
            c.drawString(320, y, str(row.get("score", "")))
            notes = (row.get("notes", "") or "").replace("\n", " ")
            c.drawString(380, y, notes[:40])
            y -= 14

    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer.read()


# -----------------------------
# UI
# -----------------------------
st.title("🧠 RTP PRO - Avaliação Funcional")
st.caption("Dr. Rodrigo Matos")

with st.expander("📌 Primeiro passo (obrigatório): criar tabelas no Supabase (SQL)", expanded=False):
    st.code(SQL_TABLES, language="sql")
    st.info("Cole esse SQL no Supabase → SQL Editor → Run.")


# -----------------------------
# Conecta no Supabase
# -----------------------------
try:
    sb = supabase_client()
except Exception as e:
    st.error(f"Falha ao iniciar Supabase: {e}")
    st.stop()


# -----------------------------
# Sidebar: busca / seleção paciente
# -----------------------------
st.sidebar.header("👤 Paciente")

search = st.sidebar.text_input("Buscar paciente (nome)", value="", placeholder="Digite parte do nome...").strip()

def load_patients():
    q = sb.table("patients").select("id, full_name, phone, created_at").order("created_at", desc=True)
    if search:
        q = q.ilike("full_name", f"%{search}%")
    res = q.execute()
    data = res.data or []
    return pd.DataFrame(data)

patients_df = pd.DataFrame()
try:
    patients_df = load_patients()
except Exception as e:
    st.error(f"Erro ao ler patients: {e}")
    st.stop()

if patients_df.empty:
    st.sidebar.warning("Nenhum paciente encontrado.")
    selected_patient_id = None
else:
    options = patients_df[["id", "full_name"]].copy()
    options["label"] = options["full_name"]
    selected_label = st.sidebar.selectbox("Selecione o paciente", options["label"].tolist())
    selected_patient_id = options.loc[options["label"] == selected_label, "id"].iloc[0]

st.sidebar.divider()
st.sidebar.subheader("➕ Cadastrar novo paciente")

with st.sidebar.form("new_patient"):
    new_name = st.text_input("Nome completo*", value="")
    new_phone = st.text_input("Telefone", value="")
    submitted = st.form_submit_button("Salvar paciente")

    if submitted:
        if not new_name.strip():
            st.sidebar.error("Nome é obrigatório.")
        else:
            try:
                sb.table("patients").insert({"full_name": new_name.strip(), "phone": new_phone.strip()}).execute()
                st.sidebar.success("Paciente cadastrado!")
                st.rerun()
            except Exception as e:
                st.sidebar.error(f"Erro ao cadastrar: {e}")


# -----------------------------
# Área principal: detalhes do paciente + avaliações
# -----------------------------
if not selected_patient_id:
    st.info("Cadastre ou selecione um paciente na barra lateral.")
    st.stop()

patient_row = patients_df.loc[patients_df["id"] == selected_patient_id].iloc[0]
patient_name = patient_row.get("full_name", "")
patient_phone = patient_row.get("phone", "")

colA, colB = st.columns([2, 3], gap="large")

with colA:
    st.subheader("📋 Dados do paciente")
    st.write(f"**Nome:** {patient_name}")
    st.write(f"**Telefone:** {patient_phone or '-'}")

    st.subheader("🧾 Nova avaliação")
    with st.form("new_assessment"):
        assessment_type = st.text_input("Tipo de avaliação*", value="RTP")
        assessment_date = st.date_input("Data*", value=date.today())
        score = st.number_input("Score*", min_value=0, max_value=1000, value=0, step=1)
        notes = st.text_area("Notas", value="", height=100)
        save_assessment = st.form_submit_button("Salvar avaliação")

        if save_assessment:
            if not assessment_type.strip():
                st.error("Tipo de avaliação é obrigatório.")
            else:
                try:
                    sb.table("assessments").insert({
                        "patient_id": str(selected_patient_id),
                        "assessment_type": assessment_type.strip(),
                        "assessment_date": str(assessment_date),
                        "score": int(score),
                        "notes": notes.strip()
                    }).execute()
                    st.success("Avaliação salva!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Erro ao salvar avaliação: {e}")

with colB:
    st.subheader("📈 Histórico de avaliações")

    def load_assessments():
        res = (
            sb.table("assessments")
            .select("id, assessment_type, assessment_date, score, notes, created_at")
            .eq("patient_id", str(selected_patient_id))
            .order("assessment_date", desc=True)
            .execute()
        )
        return pd.DataFrame(res.data or [])

    try:
        assessments_df = load_assessments()
    except Exception as e:
        st.error(f"Erro ao ler assessments: {e}")
        st.stop()

    if assessments_df.empty:
        st.info("Nenhuma avaliação registrada ainda.")
    else:
        show_df = assessments_df[["assessment_date", "assessment_type", "score", "notes"]].copy()
        st.dataframe(show_df, use_container_width=True, hide_index=True)

        st.divider()

        # Exportar PDF do paciente
        pdf_bytes = make_patient_pdf(patient_name, patient_phone, show_df)

        st.download_button(
            "📄 Baixar PDF do paciente",
            data=pdf_bytes,
            file_name=f"relatorio_{patient_name.replace(' ', '_')}.pdf",
            mime="application/pdf",
            use_container_width=True,
        )

        # Deletar avaliação (opcional)
        st.caption("🗑️ Remover uma avaliação (opcional)")
        del_id = st.selectbox("Selecione a avaliação (pelo ID)", assessments_df["id"].tolist())
        if st.button("Excluir avaliação selecionada", type="secondary"):
            try:
                sb.table("assessments").delete().eq("id", str(del_id)).execute()
                st.success("Avaliação excluída.")
                st.rerun()
            except Exception as e:
                st.error(f"Erro ao excluir: {e}")
