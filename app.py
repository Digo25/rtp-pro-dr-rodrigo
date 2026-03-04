import os
import io
import json
import hashlib
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

import streamlit as st
import pandas as pd

from supabase import create_client, Client

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import cm


# =========================
# CONFIG / PAGE
# =========================
st.set_page_config(page_title="RTP PRO – Avaliação Funcional", layout="wide")

APP_TITLE = "🧠 RTP PRO – Avaliação Funcional"
APP_SUBTITLE = "Dr. Rodrigo Matos"


# =========================
# HELPERS
# =========================
def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def secret_get(key: str, default=None):
    try:
        return st.secrets.get(key, default)
    except Exception:
        return default

def require_secret(key: str) -> Optional[str]:
    v = secret_get(key)
    if not v:
        return None
    return str(v)

def ui_banner_missing_secrets():
    st.warning("⚠️ Secrets do Supabase não configurados. Configure SUPABASE_URL e SUPABASE_SERVICE_ROLE.")
    st.info("Vá em: Streamlit → Settings → Secrets e cole as chaves. (Eu te passo o modelo abaixo.)")


# =========================
# AUTH (APP PASSWORD)
# =========================
def check_login() -> bool:
    app_pw = require_secret("APP_PASSWORD")
    if not app_pw:
        st.caption("APP_PASSWORD não definido nos Secrets. (Opcional) App está aberto.")
        return True

    if "auth_ok" not in st.session_state:
        st.session_state.auth_ok = False

    if st.session_state.auth_ok:
        return True

    with st.sidebar:
        st.subheader("🔐 Login")
        pw = st.text_input("Senha do app", type="password")
        if st.button("Entrar"):
            if pw == app_pw:
                st.session_state.auth_ok = True
                st.success("Acesso liberado ✅")
            else:
                st.error("Senha incorreta")

    return st.session_state.auth_ok


# =========================
# SUPABASE
# =========================
@st.cache_resource
def get_supabase() -> Optional[Client]:
    url = require_secret("SUPABASE_URL")
    key = require_secret("SUPABASE_SERVICE_ROLE")
    if not url or not key:
        return None
    return create_client(url, key)


def sb_select(client: Client, table: str, fields: str = "*", **eq_filters):
    q = client.table(table).select(fields)
    for k, v in eq_filters.items():
        q = q.eq(k, v)
    return q.execute()

def sb_insert(client: Client, table: str, payload: Dict[str, Any]):
    return client.table(table).insert(payload).execute()

def sb_update(client: Client, table: str, payload: Dict[str, Any], **eq_filters):
    q = client.table(table).update(payload)
    for k, v in eq_filters.items():
        q = q.eq(k, v)
    return q.execute()

def sb_delete(client: Client, table: str, **eq_filters):
    q = client.table(table).delete()
    for k, v in eq_filters.items():
        q = q.eq(k, v)
    return q.execute()


# =========================
# DB SCHEMA EXPECTED
# =========================
"""
Crie estas tabelas no Supabase (SQL):

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

Opcional: habilitar RLS e usar SERVICE_ROLE no app.
"""


# =========================
# PDF
# =========================
def generate_report_pdf(patient: Dict[str, Any], chosen: Dict[str, Any], prev: Optional[Dict[str, Any]] = None) -> io.BytesIO:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    w, h = A4

    # Header
    c.setFont("Helvetica-Bold", 16)
    c.drawString(2 * cm, h - 2 * cm, "RTP PRO – Relatório de Avaliação Funcional")

    c.setFont("Helvetica", 10)
    c.drawString(2 * cm, h - 2.8 * cm, f"Paciente: {patient.get('full_name','')}")
    c.drawString(2 * cm, h - 3.4 * cm, f"Data: {chosen.get('assessment_date','')}")
    c.drawString(2 * cm, h - 4.0 * cm, f"Tipo: {chosen.get('assessment_type','')}")
    c.drawString(2 * cm, h - 4.6 * cm, f"Score: {chosen.get('score','')}")

    # Notes
    c.setFont("Helvetica-Bold", 11)
    c.drawString(2 * cm, h - 5.6 * cm, "Observações:")
    c.setFont("Helvetica", 10)

    notes = chosen.get("notes") or ""
    y = h - 6.2 * cm
    max_width = w - 4 * cm

    # simple wrap
    words = notes.split()
    line = ""
    for wd in words:
        test = (line + " " + wd).strip()
        if c.stringWidth(test, "Helvetica", 10) <= max_width:
            line = test
        else:
            c.drawString(2 * cm, y, line)
            y -= 0.55 * cm
            line = wd
    if line:
        c.drawString(2 * cm, y, line)
        y -= 0.8 * cm

    # Comparison (optional)
    if prev:
        c.setFont("Helvetica-Bold", 11)
        c.drawString(2 * cm, y, "Comparação com avaliação anterior:")
        y -= 0.7 * cm
        c.setFont("Helvetica", 10)
        c.drawString(2 * cm, y, f"Anterior ({prev.get('assessment_date','')}): {prev.get('score','')}")
        y -= 0.55 * cm
        c.drawString(2 * cm, y, f"Atual ({chosen.get('assessment_date','')}): {chosen.get('score','')}")
        y -= 0.55 * cm

        try:
            delta = int(chosen.get("score", 0)) - int(prev.get("score", 0))
            c.drawString(2 * cm, y, f"Evolução: {delta:+d} pontos")
            y -= 0.55 * cm
        except Exception:
            pass

    # Footer
    c.setFont("Helvetica-Oblique", 9)
    c.drawString(2 * cm, 1.5 * cm, APP_SUBTITLE)

    c.showPage()
    c.save()
    buf.seek(0)
    return buf


# =========================
# UI / APP
# =========================
st.title(APP_TITLE)
st.caption(APP_SUBTITLE)

if not check_login():
    st.stop()

sb = get_supabase()
if sb is None:
    ui_banner_missing_secrets()
    st.stop()

# -------------------------
# Sidebar: Patient Search/Create
# -------------------------
st.sidebar.header("👤 Paciente")

q = st.sidebar.text_input("Buscar paciente (nome)", placeholder="Digite parte do nome")

# fetch patients
try:
    resp = sb.table("patients").select("*").order("created_at", desc=True).execute()
    patients = resp.data or []
except Exception as e:
    st.error(f"Erro ao buscar pacientes: {e}")
    st.stop()

# filter by query
if q:
    qlow = q.strip().lower()
    patients = [p for p in patients if qlow in (p.get("full_name") or "").lower()]

if len(patients) == 0:
    st.info("Nenhum paciente encontrado. Crie um novo na barra lateral.")
else:
    pass

with st.sidebar.expander("➕ Criar novo paciente", expanded=False):
    new_name = st.text_input("Nome completo", key="new_name")
    new_phone = st.text_input("Telefone (opcional)", key="new_phone")
    if st.button("Criar paciente", key="btn_create_patient"):
        if not new_name.strip():
            st.warning("Informe o nome do paciente.")
        else:
            try:
                sb_insert(sb, "patients", {"full_name": new_name.strip(), "phone": new_phone.strip() or None})
                st.success("Paciente criado ✅")
                st.rerun()
            except Exception as e:
                st.error(f"Erro ao criar paciente: {e}")

# Patient select
patient_map = {f"{p.get('full_name','(sem nome)')}": p["id"] for p in patients}
selected_patient_name = st.sidebar.selectbox("Selecionar paciente", list(patient_map.keys()) if patient_map else ["(nenhum)"])
if not patient_map:
    st.stop()

patient_id = patient_map[selected_patient_name]
patient = next(p for p in patients if p["id"] == patient_id)

st.subheader(f"Paciente: {patient.get('full_name','')}")

# -------------------------
# New Assessment
# -------------------------
st.header("🧾 Nova Avaliação")

col1, col2, col3 = st.columns([2, 1, 2])

with col1:
    assessment_type = st.selectbox(
        "Tipo de avaliação",
        ["Mobilidade", "Força", "Equilíbrio", "Flexibilidade", "Dor", "Funcional Geral"],
        index=0
    )

with col2:
    assessment_date = st.date_input("Data", value=datetime.now().date())

with col3:
    score = st.slider("Score (0–100)", min_value=0, max_value=100, value=50)

notes = st.text_area("Observações", placeholder="Escreva observações clínicas, testes, condutas...")

if st.button("Salvar avaliação", type="primary"):
    try:
        payload = {
            "patient_id": patient_id,
            "assessment_type": assessment_type,
            "assessment_date": assessment_date.isoformat(),
            "score": int(score),
            "notes": notes.strip() or None
        }
        sb_insert(sb, "assessments", payload)
        st.success("Avaliação salva ✅")
        st.rerun()
    except Exception as e:
        st.error(f"Erro ao salvar avaliação: {e}")

# -------------------------
# History
# -------------------------
st.header("📚 Histórico")

try:
    resp = sb.table("assessments").select("*").eq("patient_id", patient_id).order("assessment_date", desc=True).execute()
    items = resp.data or []
except Exception as e:
    st.error(f"Erro ao carregar histórico: {e}")
    st.stop()

if not items:
    st.info("Sem avaliações registradas para este paciente.")
    st.stop()

df = pd.DataFrame(items)
df["assessment_date"] = pd.to_datetime(df["assessment_date"], errors="coerce").dt.date
st.dataframe(
    df[["assessment_date", "assessment_type", "score", "notes"]].sort_values(by="assessment_date", ascending=False),
    use_container_width=True,
    hide_index=True
)

# -------------------------
# Select assessment to export PDF
# -------------------------
st.subheader("📄 Gerar PDF")

labels = [
    f"{x.get('assessment_date')} | {x.get('assessment_type')} | score {x.get('score')} | {str(x.get('id'))[:8]}"
    for x in items
]
idx = st.selectbox("Escolha uma avaliação para gerar PDF", list(range(len(labels))), format_func=lambda i: labels[i])
chosen = items[idx]

# previous assessment of same type (optional)
prev = None
try:
    same_type = [x for x in items if x.get("assessment_type") == chosen.get("assessment_type")]
    # items already desc by date; find chosen index and get next one
    for j, it in enumerate(same_type):
        if it.get("id") == chosen.get("id"):
            if j + 1 < len(same_type):
                prev = same_type[j + 1]
            break
except Exception:
    prev = None

pdf = generate_report_pdf(patient, chosen, prev)

st.download_button(
    "📥 Baixar PDF",
    data=pdf,
    file_name=f"RTPPRO_{patient.get('full_name','paciente')}_{chosen.get('assessment_date')}.pdf",
    mime="application/pdf"
)
