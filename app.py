import os
from datetime import date, datetime
from io import BytesIO

import streamlit as st

# -----------------------------
# Optional libs (Supabase + PDF)
# -----------------------------
try:
    from supabase import create_client
except Exception:
    create_client = None

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
except Exception:
    canvas = None
    A4 = None


# -----------------------------
# App config
# -----------------------------
st.set_page_config(page_title="RTP PRO – Avaliação Funcional", page_icon="🧠", layout="wide")
st.title("🧠 RTP PRO – Avaliação Funcional")
st.caption("Dr. Rodrigo Matos")

# -----------------------------
# Helpers
# -----------------------------
def get_secret(name: str, default: str = "") -> str:
    # tries Streamlit secrets first, then env vars
    if "secrets" in dir(st) and name in st.secrets:
        return str(st.secrets.get(name, default))
    return os.getenv(name, default)


def require_libs():
    missing = []
    if create_client is None:
        missing.append("supabase")
    if canvas is None:
        missing.append("reportlab")
    return missing


def make_pdf_report(patient_name: str, patient_phone: str, rows: list[dict]) -> bytes:
    """
    Generates a simple PDF report (bytes).
    """
    if canvas is None:
        # fallback: return a plain text file as bytes
        text = f"Paciente: {patient_name}\nTelefone: {patient_phone}\n\nAvaliações:\n"
        for r in rows:
            text += f"- {r.get('assessment_date')} | {r.get('assessment_type')} | score={r.get('score')} | {r.get('notes','')}\n"
        return text.encode("utf-8")

    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    y = height - 50
    c.setFont("Helvetica-Bold", 16)
    c.drawString(50, y, "RTP PRO – Relatório de Avaliações")
    y -= 30

    c.setFont("Helvetica", 11)
    c.drawString(50, y, f"Paciente: {patient_name}")
    y -= 18
    c.drawString(50, y, f"Telefone: {patient_phone or '-'}")
    y -= 18
    c.drawString(50, y, f"Gerado em: {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    y -= 28

    c.setFont("Helvetica-Bold", 12)
    c.drawString(50, y, "Histórico")
    y -= 18
    c.setFont("Helvetica", 10)

    if not rows:
        c.drawString(50, y, "Sem avaliações registradas.")
        y -= 14
    else:
        for r in rows:
            line = f"{r.get('assessment_date')} | {r.get('assessment_type')} | score={r.get('score')} | {r.get('notes','') or ''}"
            # wrap simple
            if len(line) > 110:
                line = line[:110] + "..."
            c.drawString(50, y, f"- {line}")
            y -= 14
            if y < 60:
                c.showPage()
                y = height - 50
                c.setFont("Helvetica", 10)

    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer.getvalue()


def supabase_client():
    url = get_secret("SUPABASE_URL").strip()
    key = get_secret("SUPABASE_SERVICE_ROLE").strip()

    if not url or not key:
        return None, "Secrets do Supabase não configurados. Configure SUPABASE_URL e SUPABASE_SERVICE_ROLE."
    if create_client is None:
        return None, "Biblioteca supabase não instalada (dependência)."

    try:
        return create_client(url, key), ""
    except Exception as e:
        return None, f"Erro ao conectar no Supabase: {e}"


# -----------------------------
# Sidebar (patient search)
# -----------------------------
st.sidebar.header("👤 Paciente")

sb, err = supabase_client()
if err:
    st.warning(err)
    st.info("Vá em: Streamlit → Settings → Secrets e cole as chaves em formato TOML (modelo abaixo).")
    st.code(
        'SUPABASE_URL = "https://SEU-PROJETO.supabase.co"\n'
        'SUPABASE_SERVICE_ROLE = "SUA_SERVICE_ROLE_KEY"\n',
        language="toml",
    )
    missing = require_libs()
    if missing:
        st.info(f"Dependências ausentes: {', '.join(missing)}. Verifique seu requirements.txt.")
    st.stop()

# Patient search box
q = st.sidebar.text_input("Buscar paciente (nome)", value="", placeholder="Digite parte do nome...")
patients = []
try:
    if q.strip():
        res = sb.table("patients").select("*").ilike("full_name", f"%{q.strip()}%").order("full_name").limit(20).execute()
    else:
        res = sb.table("patients").select("*").order("created_at", desc=True).limit(20).execute()
    patients = res.data or []
except Exception as e:
    st.error(f"Erro ao ler patients: {e}")
    st.stop()

patient_labels = ["(Novo paciente)"] + [f"{p.get('full_name','(sem nome)')}  •  {p.get('phone','')}" for p in patients]
choice = st.sidebar.selectbox("Selecionar", patient_labels, index=0)

selected_patient = None
if choice != "(Novo paciente)":
    idx = patient_labels.index(choice) - 1
    selected_patient = patients[idx]

st.sidebar.divider()

# Create / update patient
with st.sidebar.expander("➕ Criar/editar paciente", expanded=(selected_patient is None)):
    full_name = st.text_input("Nome completo", value=(selected_patient.get("full_name") if selected_patient else ""))
    phone = st.text_input("Telefone", value=(selected_patient.get("phone") if selected_patient else ""))

    colA, colB = st.columns(2)
    with colA:
        save_patient = st.button("Salvar", use_container_width=True)
    with colB:
        delete_patient = st.button("Excluir", use_container_width=True, disabled=(selected_patient is None))

    if save_patient:
        if not full_name.strip():
            st.sidebar.error("Nome é obrigatório.")
        else:
            try:
                if selected_patient is None:
                    ins = sb.table("patients").insert({"full_name": full_name.strip(), "phone": phone.strip()}).execute()
                    st.sidebar.success("Paciente criado.")
                    st.rerun()
                else:
                    sb.table("patients").update({"full_name": full_name.strip(), "phone": phone.strip()}).eq("id", selected_patient["id"]).execute()
                    st.sidebar.success("Paciente atualizado.")
                    st.rerun()
            except Exception as e:
                st.sidebar.error(f"Erro ao salvar paciente: {e}")

    if delete_patient and selected_patient is not None:
        try:
            sb.table("patients").delete().eq("id", selected_patient["id"]).execute()
            st.sidebar.success("Paciente excluído.")
            st.rerun()
        except Exception as e:
            st.sidebar.error(f"Erro ao excluir paciente: {e}")


# -----------------------------
# Main area
# -----------------------------
col1, col2 = st.columns([1.2, 1])

with col1:
    st.subheader("📝 Registrar Avaliação")

    if selected_patient is None:
        st.info("Selecione um paciente na barra lateral (ou crie um novo) para registrar avaliações.")
    else:
        atype = st.selectbox("Tipo de avaliação", ["RTP", "Funcional", "Dor/Qualidade de Vida", "Outro"])
        adate = st.date_input("Data", value=date.today())
        score = st.number_input("Score", min_value=0, max_value=100, value=0, step=1)
        notes = st.text_area("Observações", placeholder="Opcional...")

        save_assessment = st.button("Salvar avaliação", type="primary")
        if save_assessment:
            try:
                sb.table("assessments").insert(
                    {
                        "patient_id": selected_patient["id"],
                        "assessment_type": atype,
                        "assessment_date": str(adate),
                        "score": int(score),
                        "notes": notes.strip(),
                    }
                ).execute()
                st.success("Avaliação salva.")
                st.rerun()
            except Exception as e:
                st.error(f"Erro ao salvar avaliação: {e}")

with col2:
    st.subheader("📚 Histórico + PDF")

    if selected_patient is None:
        st.info("Sem paciente selecionado.")
    else:
        try:
            res = (
                sb.table("assessments")
                .select("*")
                .eq("patient_id", selected_patient["id"])
                .order("assessment_date", desc=True)
                .limit(200)
                .execute()
            )
            rows = res.data or []
        except Exception as e:
            st.error(f"Erro ao buscar histórico: {e}")
            rows = []

        if rows:
            st.dataframe(
                [
                    {
                        "Data": r.get("assessment_date"),
                        "Tipo": r.get("assessment_type"),
                        "Score": r.get("score"),
                        "Obs": r.get("notes", ""),
                    }
                    for r in rows
                ],
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.write("Sem avaliações ainda.")

        pdf_bytes = make_pdf_report(
            patient_name=selected_patient.get("full_name", ""),
            patient_phone=selected_patient.get("phone", ""),
            rows=rows,
        )

        st.download_button(
            label="📄 Baixar relatório (PDF)",
            data=pdf_bytes,
            file_name=f"relatorio_{selected_patient.get('full_name','paciente').replace(' ','_')}.pdf",
            mime="application/pdf",
        )


# -----------------------------
# Footer: show SQL to create tables
# -----------------------------
with st.expander("🧱 SQL para criar as tabelas no Supabase", expanded=False):
    st.code(
        """
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
        """.strip(),
        language="sql",
    )
