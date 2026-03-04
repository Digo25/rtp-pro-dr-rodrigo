import os
import io
import json
from datetime import date, datetime
from dateutil.relativedelta import relativedelta

import streamlit as st
import pandas as pd

from supabase import create_client, Client
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import cm


# =========================
# CONFIG
# =========================
st.set_page_config(
    page_title="RTP PRO - Avaliação Funcional",
    layout="wide",
)

APP_TITLE = "🧠 RTP PRO – Avaliação Funcional"
APP_SUBTITLE = "Dr. Rodrigo Matos"

SUPABASE_URL = st.secrets.get("SUPABASE_URL", "")
SUPABASE_SERVICE_ROLE = st.secrets.get("SUPABASE_SERVICE_ROLE", "")
APP_PASSWORD = st.secrets.get("APP_PASSWORD", "")

REQUIRE_AUTH = True  # mantém privado mesmo que Streamlit Sharing esteja aberto

# Normas/referências (configurável)
# *Não é “diagnóstico”; é comparação automatizada com faixas de referência configuráveis.*
DEFAULT_NORMS = {
    "pain": {"low": [0, 3], "moderate": [4, 6], "high": [7, 10]},
    "strength": {"low": [0, 3], "moderate": [4, 6], "good": [7, 10]},
    "mobility": {"low": [0, 3], "moderate": [4, 6], "good": [7, 10]},
    "conditioning_index": {"poor": [0, 39], "average": [40, 69], "good": [70, 100]},
    "risk_score": {"low": [0, 29], "moderate": [30, 59], "high": [60, 100]},
}

# =========================
# HELPERS
# =========================
def supabase() -> Client:
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE:
        st.error("Secrets do Supabase não configurados. Configure SUPABASE_URL e SUPABASE_SERVICE_ROLE.")
        st.stop()
    return create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE)

def calc_age(birth_date: date | None) -> int | None:
    if not birth_date:
        return None
    return relativedelta(date.today(), birth_date).years

def bucket_label(value: float | int | None, buckets: dict) -> str:
    if value is None:
        return "não informado"
    for name, rng in buckets.items():
        lo, hi = rng
        if lo <= value <= hi:
            return name
    return "fora da faixa"

def safe_int(x):
    try:
        if x is None or x == "":
            return None
        return int(x)
    except:
        return None

def safe_float(x):
    try:
        if x is None or x == "":
            return None
        return float(x)
    except:
        return None

def compute_conditioning_index(cardio: dict, motor: dict, plyo: dict) -> float | None:
    """
    Índice 0-100 baseado no que estiver preenchido.
    """
    scores = []
    # cardio
    if cardio:
        vo2 = safe_float(cardio.get("vo2_est"))
        hrrec = safe_float(cardio.get("hr_recovery_1min"))
        if vo2 is not None:
            scores.append(min(100, max(0, (vo2 / 60) * 100)))  # heurística
        if hrrec is not None:
            scores.append(min(100, max(0, (hrrec / 40) * 100)))  # heurística
    # motor control
    if motor:
        mscore = safe_float(motor.get("motor_control_score"))
        if mscore is not None:
            scores.append(min(100, max(0, mscore)))
    # plyo
    if plyo:
        rsi = safe_float(plyo.get("rsi"))
        if rsi is not None:
            scores.append(min(100, max(0, (rsi / 3.0) * 100)))  # heurística

    if not scores:
        return None
    return round(sum(scores) / len(scores), 1)

def compute_risk_score(pain, mobility, strength, combined: dict, posture: dict, plyo: dict, motor: dict) -> float | None:
    """
    Escore 0-100 (quanto maior, maior risco).
    Só usa o que estiver preenchido.
    """
    parts = []

    # Dor
    if pain is not None:
        parts.append((pain / 10) * 30)  # até 30 pts

    # Mobilidade/força baixos aumentam risco
    if mobility is not None:
        parts.append(((10 - mobility) / 10) * 20)  # até 20
    if strength is not None:
        parts.append(((10 - strength) / 10) * 20)  # até 20

    # Movimentos combinados: se indicar dor em combos, aumenta
    if combined:
        flags = combined.get("pain_triggers", [])
        if isinstance(flags, list) and len(flags) > 0:
            parts.append(min(20, 5 * len(flags)))  # até 20

    # Postura/RPG: se marcou desequilíbrios, aumenta
    if posture:
        imbalances = posture.get("imbalances", [])
        if isinstance(imbalances, list) and len(imbalances) > 0:
            parts.append(min(15, 3 * len(imbalances)))  # até 15 (mas vai somar, depois clamp)

    # Pliometria: se RSI muito baixo ou assimetria alta
    if plyo:
        asym = safe_float(plyo.get("asymmetry_pct"))
        if asym is not None and asym >= 10:
            parts.append(min(20, (asym / 30) * 20))

    # Controle motor baixo
    if motor:
        mscore = safe_float(motor.get("motor_control_score"))
        if mscore is not None and mscore < 60:
            parts.append(min(15, ((60 - mscore) / 60) * 15))

    if not parts:
        return None
    return round(min(100, sum(parts)), 1)

def compute_muscle_mass_index(joint_muscle: dict) -> float | None:
    """
    IM muscular (campo/estimativa) – se tiver.
    """
    if not joint_muscle:
        return None
    val = safe_float(joint_muscle.get("muscle_mass_index"))
    if val is None:
        return None
    return round(val, 2)

def generate_report_pdf(patient: dict, assessment: dict, comparison: dict | None = None) -> bytes:
    """
    Gera PDF mesmo com campos em branco.
    """
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    w, h = A4

    def line(y, text, size=11, bold=False):
        c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        c.drawString(2*cm, y, str(text)[:120])

    y = h - 2*cm
    line(y, "RTP PRO – Relatório de Avaliação Funcional", 14, True); y -= 0.8*cm
    line(y, f"Profissional: {APP_SUBTITLE}", 11); y -= 0.6*cm
    line(y, f"Data: {assessment.get('assessment_date', '')}  |  Tipo: {assessment.get('assessment_type','')}", 11); y -= 0.8*cm

    line(y, f"Paciente: {patient.get('full_name','')}", 12, True); y -= 0.6*cm
    line(y, f"Nascimento: {patient.get('birth_date','')}  |  Idade: {calc_age(patient.get('birth_date'))}", 10); y -= 0.6*cm

    pain = assessment.get("pain_level")
    mobility = assessment.get("mobility")
    strength = assessment.get("strength")
    conditioning = assessment.get("conditioning_index")
    mmi = assessment.get("muscle_mass_index")
    risk = assessment.get("risk_score")

    y -= 0.2*cm
    line(y, "Resumo e Índices", 12, True); y -= 0.6*cm
    line(y, f"Dor: {pain if pain is not None else '—'} ({bucket_label(pain, DEFAULT_NORMS['pain'])})", 10); y -= 0.45*cm
    line(y, f"Mobilidade: {mobility if mobility is not None else '—'} ({bucket_label(mobility, DEFAULT_NORMS['mobility'])})", 10); y -= 0.45*cm
    line(y, f"Força: {strength if strength is not None else '—'} ({bucket_label(strength, DEFAULT_NORMS['strength'])})", 10); y -= 0.45*cm
    line(y, f"Índice de Condicionamento Físico: {conditioning if conditioning is not None else '—'} ({bucket_label(conditioning, DEFAULT_NORMS['conditioning_index'])})", 10); y -= 0.45*cm
    line(y, f"Índice de Massa Muscular: {mmi if mmi is not None else '—'}", 10); y -= 0.45*cm
    line(y, f"Risco de Lesão/Recidiva: {risk if risk is not None else '—'} ({bucket_label(risk, DEFAULT_NORMS['risk_score'])})", 10); y -= 0.7*cm

    obs = assessment.get("observations") or ""
    line(y, "Observações", 12, True); y -= 0.6*cm
    for chunk in [obs[i:i+95] for i in range(0, len(obs), 95)]:
        line(y, chunk, 10); y -= 0.45*cm
        if y < 3*cm:
            c.showPage()
            y = h - 2*cm

    # Comparação (se existir)
    if comparison:
        if y < 6*cm:
            c.showPage(); y = h - 2*cm
        y -= 0.2*cm
        line(y, "Comparação com avaliação anterior", 12, True); y -= 0.6*cm
        for k, v in comparison.items():
            line(y, f"{k}: {v}", 10); y -= 0.45*cm
            if y < 3*cm:
                c.showPage(); y = h - 2*cm

    c.showPage()
    c.save()
    return buf.getvalue()

def require_login():
    if not REQUIRE_AUTH:
        return
    if not APP_PASSWORD:
        st.warning("APP_PASSWORD não definido no Secrets. Defina para manter privado.")
        return

    if st.session_state.get("authed") is True:
        return

    st.title(APP_TITLE)
    st.caption("Acesso restrito")
    pwd = st.text_input("Senha do aplicativo", type="password")
    if st.button("Entrar"):
        if pwd == APP_PASSWORD:
            st.session_state["authed"] = True
            st.success("Acesso liberado.")
            st.rerun()
        else:
            st.error("Senha incorreta.")
    st.stop()


# =========================
# DB ACTIONS
# =========================
def db_get_patients(q: str = ""):
    sb = supabase()
    if q:
        res = sb.table("patients").select("*").ilike("full_name", f"%{q}%").order("full_name").execute()
    else:
        res = sb.table("patients").select("*").order("full_name").limit(50).execute()
    return res.data or []

def db_create_patient(payload: dict):
    sb = supabase()
    res = sb.table("patients").insert(payload).execute()
    return (res.data or [None])[0]

def db_create_episode(payload: dict):
    sb = supabase()
    res = sb.table("episodes").insert(payload).execute()
    return (res.data or [None])[0]

def db_get_open_episode(patient_id: str):
    sb = supabase()
    res = sb.table("episodes").select("*").eq("patient_id", patient_id).eq("status", "open").order("created_at", desc=True).limit(1).execute()
    data = res.data or []
    return data[0] if data else None

def db_list_assessments(patient_id: str):
    sb = supabase()
    res = sb.table("assessments").select("*").eq("patient_id", patient_id).order("assessment_date", desc=True).execute()
    return res.data or []

def db_insert_assessment(payload: dict):
    sb = supabase()
    res = sb.table("assessments").insert(payload).execute()
    return (res.data or [None])[0]

def db_upload_photo(assessment_id: str, photo_type: str, file, notes: str = ""):
    sb = supabase()
    # Upload to Storage
    ext = "jpg"
    name = getattr(file, "name", "") or "photo.jpg"
    if "." in name:
        ext = name.split(".")[-1].lower()
    path = f"{assessment_id}/{photo_type}_{int(datetime.utcnow().timestamp())}.{ext}"

    data = file.read()
    sb.storage.from_("assessment-photos").upload(path, data, {"content-type": file.type if hasattr(file, "type") else "image/jpeg"})

    # Store reference in DB
    row = {
        "assessment_id": assessment_id,
        "photo_type": photo_type,
        "storage_path": path,
        "notes": notes
    }
    sb.table("assessment_photos").insert(row).execute()
    return path

def db_get_last_assessment(patient_id: str, assessment_type: str, exclude_id: str | None = None):
    sb = supabase()
    q = sb.table("assessments").select("*").eq("patient_id", patient_id).eq("assessment_type", assessment_type).order("assessment_date", desc=True).limit(5)
    res = q.execute()
    items = res.data or []
    for it in items:
        if exclude_id and it["id"] == exclude_id:
            continue
        return it
    return None


# =========================
# UI SECTIONS
# =========================
def section_patient_picker():
    st.sidebar.header("👤 Paciente")
    q = st.sidebar.text_input("Buscar paciente (nome)", value="")
    pts = db_get_patients(q)

    if not pts:
        st.sidebar.info("Nenhum paciente encontrado.")
        chosen = None
    else:
        labels = [f"{p['full_name']} — {p['id'][:8]}" for p in pts]
        idx = st.sidebar.selectbox("Selecione", list(range(len(labels))), format_func=lambda i: labels[i])
        chosen = pts[idx]

    with st.sidebar.expander("➕ Cadastrar novo paciente", expanded=False):
        name = st.text_input("Nome completo")
        birth = st.date_input("Data de nascimento", value=None)
        sex = st.selectbox("Sexo", ["", "M", "F", "Outro"])
        phone = st.text_input("Telefone")
        email = st.text_input("E-mail")
        notes = st.text_area("Observações do paciente")
        if st.button("Salvar paciente"):
            if not name.strip():
                st.error("Informe o nome.")
            else:
                payload = {
                    "full_name": name.strip(),
                    "birth_date": birth.isoformat() if birth else None,
                    "sex": sex or None,
                    "phone": phone or None,
                    "email": email or None,
                    "notes": notes or None
                }
                p = db_create_patient(payload)
                st.success("Paciente criado.")
                st.session_state["patient_id"] = p["id"]
                st.rerun()

    if chosen:
        st.session_state["patient_id"] = chosen["id"]
    return chosen

def section_assessment_selector():
    st.sidebar.header("🧭 Menu")
    menu = st.sidebar.radio(
        "Escolha",
        ["Nova avaliação", "Histórico", "Comparação", "Relatórios"],
        index=0
    )

    st.sidebar.header("🧪 Escolha a avaliação")
    assessment_type = st.sidebar.selectbox(
        "Tipo",
        ["Avaliação Rápida", "Avaliação Completa"],
        index=0
    )
    st.session_state["assessment_type"] = "quick" if assessment_type == "Avaliação Rápida" else "full"
    return menu, st.session_state["assessment_type"]

def form_quick():
    st.subheader("⚡ Avaliação Rápida")
    col1, col2 = st.columns([2, 1], vertical_alignment="top")
    with col1:
        name = st.text_input("Nome do paciente (apenas para conferência no relatório)", value="")
        pain = st.slider("Nível de dor (0-10)", 0, 10, 5)
        strength = st.slider("Força muscular (0-10)", 0, 10, 5)
        obs = st.text_area("Observações", height=120)
    with col2:
        st.info("Rápida = triagem + índices + relatório. Você pode anexar fotos e testes rápidos abaixo.")

    # Blocos rápidos (inclui biomecânica por foto, controle motor, pliometria, cardio)
    with st.expander("📸 Biomecânica por fotos (rápido)", expanded=True):
        posture_front = st.file_uploader("Foto postura (frente)", type=["jpg", "jpeg", "png"], key="q_posture_front")
        posture_side = st.file_uploader("Foto postura (perfil)", type=["jpg", "jpeg", "png"], key="q_posture_side")
        facial = st.file_uploader("Foto facial (se aplicável)", type=["jpg", "jpeg", "png"], key="q_facial")
        photo_notes = st.text_area("Notas das fotos", key="q_photo_notes")

    with st.expander("🧠 Controle motor (rápido)", expanded=False):
        mc_score = st.slider("Score controle motor (0-100)", 0, 100, 70)
        mc_notes = st.text_area("Observações controle motor", key="q_mc_notes")

    with st.expander("🦘 Pliometria (rápido)", expanded=False):
        jump_cm = st.number_input("Salto vertical (cm)", min_value=0.0, step=0.5, value=0.0)
        rsi = st.number_input("RSI (Reactive Strength Index)", min_value=0.0, step=0.1, value=0.0)
        asym = st.number_input("Assimetria (%)", min_value=0.0, step=0.5, value=0.0)

    with st.expander("❤️ Cardiovascular (rápido)", expanded=False):
        vo2_est = st.number_input("VO2 estimado (ml/kg/min)", min_value=0.0, step=0.5, value=0.0)
        hr_rest = st.number_input("FC repouso", min_value=0.0, step=1.0, value=0.0)
        hr_rec = st.number_input("Recuperação FC 1min (bpm)", min_value=0.0, step=1.0, value=0.0)

    # Exames (rápido) – campos, não “prescrição”
    with st.expander("🧪 Exames laboratoriais (rápido)", expanded=False):
        labs = {
            "cpk": st.text_input("CPK (se tiver)"),
            "crp": st.text_input("PCR/CRP"),
            "esr": st.text_input("VHS/ESR"),
            "rf": st.text_input("Fator reumatoide (RF)"),
            "anti_ccp": st.text_input("Anti-CCP"),
            "vit_d": st.text_input("Vitamina D"),
            "notes": st.text_area("Notas de exames", height=80),
        }

    return {
        "display_name": name,
        "pain": pain,
        "mobility": None,
        "strength": strength,
        "observations": obs,
        "photos": {
            "posture_front": posture_front,
            "posture_side": posture_side,
            "facial": facial,
            "notes": photo_notes,
        },
        "motor_control": {"motor_control_score": mc_score, "notes": mc_notes},
        "plyometrics": {"jump_cm": jump_cm, "rsi": rsi, "asymmetry_pct": asym},
        "cardiovascular": {"vo2_est": vo2_est, "hr_rest": hr_rest, "hr_recovery_1min": hr_rec},
        "labs": labs,
    }

def form_full():
    st.subheader("📋 Avaliação Completa")
    st.caption("Organizada por seções: dor/queixa, postural (RPG/cadeias), movimentos combinados (causa da dor), biomecânica por fotos, músculo-articular, cardiovascular, controle motor universal, pliometria e exames.")

    top1, top2 = st.columns([2, 1], vertical_alignment="top")
    with top1:
        name = st.text_input("Nome do paciente (apenas para conferência no relatório)", value="")
        age = st.number_input("Idade", min_value=0, max_value=120, value=30)
        pathology = st.text_input("Patologia principal")
        chief = st.text_input("Queixa principal")
        pain = st.slider("Nível de dor (0-10)", 0, 10, 5)
        mobility = st.slider("Mobilidade (0-10)", 0, 10, 5)
        strength = st.slider("Força muscular (0-10)", 0, 10, 5)
        obs = st.text_area("Observações clínicas", height=120)
    with top2:
        st.info("A avaliação completa habilita comparação, índices e relatório profissional, mesmo com campos em branco.")

    with st.expander("🧭 Avaliação Postural (RPG / Cadeias Musculares)", expanded=True):
        chain = st.multiselect(
            "Cadeias com suspeita de encurtamento / tensão",
            ["Cadeia posterior", "Cadeia anterior", "Cadeia inspiratória", "Cadeias cruzadas", "Cadeia lateral"],
        )
        imbalances = st.multiselect(
            "Pontos de desequilíbrio (marque o que observar)",
            ["Anteversão pélvica", "Retroversão pélvica", "Hipercifose", "Hiperlordose", "Escoliose", "Valgo joelho", "Varo joelho", "Pé pronado", "Pé supinado", "Ombro anteriorizado", "Cabeça anteriorizada"]
        )
        rpg_notes = st.text_area("Notas (método RPG / postura)", height=90)
        posture_rpg = {"chains": chain, "imbalances": imbalances, "notes": rpg_notes}

    with st.expander("🧩 Causa da Dor – Movimentos Combinados (rastreamento)", expanded=True):
        triggers = st.multiselect(
            "Movimentos/combinações que provocam dor",
            ["Flexão + rotação", "Extensão + rotação", "Abdução + rotação", "Agachamento + rotação", "Elevação braço + rotação", "Marcha/corrida", "Saltos", "Apoio unilateral", "Subir escadas"]
        )
        region = st.multiselect(
            "Regiões suspeitas de origem (hipótese clínica)",
            ["Coluna cervical", "Coluna torácica", "Coluna lombar", "Quadril", "Joelho", "Tornozelo/pé", "Ombro", "Cotovelo", "Punho/mão", "ATM"]
        )
        combo_notes = st.text_area("Notas de testes combinados e hipótese de origem", height=90)
        combined = {"pain_triggers": triggers, "suspected_origin_regions": region, "notes": combo_notes}

    with st.expander("📸 Biomecânica por Fotos (postura / marcha / articular / facial)", expanded=True):
        posture_front = st.file_uploader("Foto postura (frente)", type=["jpg", "jpeg", "png"], key="f_posture_front")
        posture_side = st.file_uploader("Foto postura (perfil)", type=["jpg", "jpeg", "png"], key="f_posture_side")
        gait = st.file_uploader("Foto/vídeo (marcha) – se usar imagem, envie frame", type=["jpg", "jpeg", "png"], key="f_gait")
        joint = st.file_uploader("Foto articular específica", type=["jpg", "jpeg", "png"], key="f_joint")
        facial = st.file_uploader("Foto facial", type=["jpg", "jpeg", "png"], key="f_facial")
        bio_notes = st.text_area("Notas biomecânicas (observação)", height=90)
        biomechanics = {"notes": bio_notes}

    with st.expander("🦴 Avaliação Muscular / Articular / Funcional", expanded=False):
        rom = st.text_area("ADM / ROM (descrição)", height=90)
        strength_map = st.text_area("Força segmentar (ex.: glúteo médio, manguito, etc.)", height=90)
        functional_tests = st.multiselect(
            "Testes funcionais realizados",
            ["Y-Balance", "Single Leg Squat", "Step Down", "Hop Test", "Agachamento", "Prancha", "Ponte", "Lunge", "Overhead Squat"]
        )
        joint_muscle = {
            "rom": rom,
            "strength_map": strength_map,
            "functional_tests": functional_tests,
            "muscle_mass_index": st.text_input("Índice de massa muscular (atual) – se tiver"),
            "muscle_mass_expected": st.text_input("Índice de massa muscular (esperado) – se usar referência"),
        }

    with st.expander("🧠 Controle Motor Universal (focado)", expanded=False):
        mc_score = st.slider("Score controle motor (0-100)", 0, 100, 70)
        mc_deficits = st.multiselect(
            "Déficits observados",
            ["Estabilidade lombo-pélvica", "Controle escápulo-umeral", "Propriocepção tornozelo", "Controle valgo dinâmico", "Coordenação", "Tempo de reação"]
        )
        mc_notes = st.text_area("Notas controle motor", height=90)
        motor_control = {"motor_control_score": mc_score, "deficits": mc_deficits, "notes": mc_notes}

    with st.expander("🦘 Pliometria (completa)", expanded=False):
        jump_cm = st.number_input("Salto vertical (cm)", min_value=0.0, step=0.5, value=0.0, key="f_jump")
        rsi = st.number_input("RSI", min_value=0.0, step=0.1, value=0.0, key="f_rsi")
        asym = st.number_input("Assimetria (%)", min_value=0.0, step=0.5, value=0.0, key="f_asym")
        plyo_notes = st.text_area("Notas pliometria", height=80)
        plyo = {"jump_cm": jump_cm, "rsi": rsi, "asymmetry_pct": asym, "notes": plyo_notes}

    with st.expander("❤️ Cardiovascular (completa)", expanded=False):
        vo2_est = st.number_input("VO2 estimado", min_value=0.0, step=0.5, value=0.0, key="f_vo2")
        hr_rest = st.number_input("FC repouso", min_value=0.0, step=1.0, value=0.0, key="f_hrrest")
        hr_rec = st.number_input("Recuperação FC 1min", min_value=0.0, step=1.0, value=0.0, key="f_hrrec")
        cardio_notes = st.text_area("Notas cardio", height=80)
        cardio = {"vo2_est": vo2_est, "hr_rest": hr_rest, "hr_recovery_1min": hr_rec, "notes": cardio_notes}

    with st.expander("🧪 Exames laboratoriais (muscular / articular / reumato / inflamatório)", expanded=False):
        labs = {
            "cpk": st.text_input("CPK"),
            "crp": st.text_input("PCR/CRP"),
            "esr": st.text_input("VHS/ESR"),
            "rf": st.text_input("Fator reumatoide (RF)"),
            "anti_ccp": st.text_input("Anti-CCP"),
            "ana": st.text_input("FAN/ANA"),
            "uric_acid": st.text_input("Ácido úrico"),
            "vit_d": st.text_input("Vitamina D"),
            "notes": st.text_area("Notas de exames", height=80),
        }

    with st.expander("🙂 Avaliação Facial (se aplicável)", expanded=False):
        facial_notes = st.text_area("Observações faciais (simetria, dor, tensão, etc.)", height=90)
        facial_json = {"notes": facial_notes}

    photos = {
        "posture_front": posture_front,
        "posture_side": posture_side,
        "gait": gait,
        "joint": joint,
        "facial": facial,
    }

    return {
        "display_name": name,
        "age": age,
        "pathology": pathology,
        "chief": chief,
        "pain": pain,
        "mobility": mobility,
        "strength": strength,
        "observations": obs,
        "posture_rpg": posture_rpg,
        "combined": combined,
        "biomechanics": biomechanics,
        "photos": photos,
        "joint_muscle": joint_muscle,
        "motor_control": motor_control,
        "plyometrics": plyo,
        "cardiovascular": cardio,
        "labs": labs,
        "facial": facial_json,
    }

def build_comparison(prev: dict, current: dict) -> dict:
    out = {}
    def delta(field, label):
        a = prev.get(field)
        b = current.get(field)
        if a is None or b is None:
            return
        out[label] = f"{a} → {b} ({'melhora' if b < a and field=='pain_level' else 'variação'})"

    delta("pain_level", "Dor")
    delta("mobility", "Mobilidade")
    delta("strength", "Força")
    delta("conditioning_index", "Condicionamento")
    delta("risk_score", "Risco")

    return out

def save_assessment(patient: dict, assessment_type: str, data: dict):
    # episode
    ep = db_get_open_episode(patient["id"])
    if not ep:
        ep = db_create_episode({
            "patient_id": patient["id"],
            "chief_complaint": data.get("chief") or None,
            "main_pathology": data.get("pathology") or None
        })

    # compute indices
    pain = data.get("pain")
    mobility = data.get("mobility")
    strength = data.get("strength")
    cardio = data.get("cardiovascular") or {}
    motor = data.get("motor_control") or {}
    plyo = data.get("plyometrics") or {}

    conditioning_index = compute_conditioning_index(cardio, motor, plyo)
    muscle_mass_index = compute_muscle_mass_index(data.get("joint_muscle") or {})
    risk_score = compute_risk_score(pain, mobility, strength, data.get("combined") or {}, data.get("posture_rpg") or {}, plyo, motor)

    payload = {
        "patient_id": patient["id"],
        "episode_id": ep["id"],
        "assessment_type": assessment_type,
        "assessment_date": date.today().isoformat(),
        "pain_level": safe_int(pain),
        "mobility": safe_int(mobility),
        "strength": safe_int(strength),
        "observations": data.get("observations") or None,
        "conditioning_index": conditioning_index,
        "muscle_mass_index": muscle_mass_index,
        "risk_score": risk_score,
        "biomechanics": data.get("biomechanics") or None,
        "posture_rpg": data.get("posture_rpg") or None,
        "combined_movements": data.get("combined") or None,
        "cardiovascular": data.get("cardiovascular") or None,
        "motor_control": data.get("motor_control") or None,
        "plyometrics": data.get("plyometrics") or None,
        "labs": data.get("labs") or None,
        "facial": data.get("facial") or None,
        "joint_muscle": data.get("joint_muscle") or None,
        "report_summary": None,
    }

    saved = db_insert_assessment(payload)

    # upload photos (if any)
    photos = data.get("photos") or {}
    for ptype, file in photos.items():
        if file is not None:
            notes = ""
            if "notes" in photos:
                notes = photos.get("notes") or ""
            db_upload_photo(saved["id"], ptype, file, notes=notes)

    # compare with previous
    prev = db_get_last_assessment(patient["id"], assessment_type, exclude_id=saved["id"])
    comparison = build_comparison(prev, saved) if prev else None

    # generate pdf
    pdf = generate_report_pdf(patient, saved, comparison)

    return saved, pdf


# =========================
# MAIN
# =========================
require_login()

st.title(APP_TITLE)
st.caption(APP_SUBTITLE)

patient = section_patient_picker()
menu, assessment_type = section_assessment_selector()

if not patient:
    st.info("Selecione ou cadastre um paciente na barra lateral.")
    st.stop()

if menu == "Nova avaliação":
    st.divider()
    if assessment_type == "quick":
        data = form_quick()
        btn = st.button("💾 Salvar avaliação rápida", use_container_width=True)
    else:
        data = form_full()
        btn = st.button("💾 Salvar avaliação completa", use_container_width=True)

    if btn:
        saved, pdf = save_assessment(patient, assessment_type, data)
        st.success("Avaliação salva com sucesso.")
        st.download_button(
            "📄 Baixar relatório PDF",
            data=pdf,
            file_name=f"RTPPRO_{patient['full_name']}_{saved['assessment_date']}_{assessment_type}.pdf",
            mime="application/pdf"
        )

        st.subheader("📊 Resultado Profissional (automático)")
        st.write({
            "Dor": saved.get("pain_level"),
            "Mobilidade": saved.get("mobility"),
            "Força": saved.get("strength"),
            "Índice de Condicionamento": saved.get("conditioning_index"),
            "Índice de Massa Muscular": saved.get("muscle_mass_index"),
            "Risco (lesão/recidiva)": saved.get("risk_score"),
        })

elif menu == "Histórico":
    st.divider()
    st.subheader("📚 Histórico do paciente")
    items = db_list_assessments(patient["id"])
    if not items:
        st.info("Sem avaliações ainda.")
    else:
        df = pd.DataFrame(items)
        show_cols = ["assessment_date", "assessment_type", "pain_level", "mobility", "strength", "conditioning_index", "risk_score", "created_at"]
        show_cols = [c for c in show_cols if c in df.columns]
        st.dataframe(df[show_cols], use_container_width=True)

elif menu == "Comparação":
    st.divider()
    st.subheader("📈 Comparação de evolução")
    items = db_list_assessments(patient["id"])
    if len(items) < 2:
        st.info("Você precisa de pelo menos 2 avaliações para comparar.")
    else:
        # pick type
        t = st.selectbox("Tipo", ["quick", "full"], format_func=lambda x: "Avaliação Rápida" if x=="quick" else "Avaliação Completa")
        typed = [x for x in items if x["assessment_type"] == t]
        if len(typed) < 2:
            st.info("Sem 2 avaliações desse tipo ainda.")
        else:
            a = typed[0]
            b = typed[1]
            comp = build_comparison(b, a)
            st.write("Última vs anterior:")
            st.json(comp)

elif menu == "Relatórios":
    st.divider()
    st.subheader("🧾 Relatórios")
    items = db_list_assessments(patient["id"])
    if not items:
        st.info("Sem avaliações ainda.")
    else:
        labels = [f"{x['assessment_date']} | {x['assessment_type']} | {x['id'][:8]}" for x in items]
idx = st.selectbox(
    "Escolha uma avaliação para gerar PDF novamente",
    list(range(len(items)))
)

chosen = items[idx]

prev = db_get_last_assessment(
    patient["id"],
    chosen["assessment_type"],
    exclude_id=chosen["id"]
)

comp = build_comparison(prev, chosen) if prev else None

pdf = generate_report_pdf(patient, chosen, comp)

st.download_button(
    "Baixar PDF",
    data=pdf,
    file_name=f"RTPPRO_{patient['full_name']}_{chosen['assessment_date']}.pdf",
    mime="application/pdf"
)
import os
import io
import json
from datetime import date, datetime
from dateutil.relativedelta import relativedelta

import streamlit as st
import pandas as pd

from supabase import create_client, Client
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import cm


# =========================
# CONFIG
# =========================
st.set_page_config(
    page_title="RTP PRO - Avaliação Funcional",
    layout="wide",
)

APP_TITLE = "🧠 RTP PRO – Avaliação Funcional"
APP_SUBTITLE = "Dr. Rodrigo Matos"

SUPABASE_URL = st.secrets.get("SUPABASE_URL", "")
SUPABASE_SERVICE_ROLE = st.secrets.get("SUPABASE_SERVICE_ROLE", "")
APP_PASSWORD = st.secrets.get("APP_PASSWORD", "")

REQUIRE_AUTH = True  # mantém privado mesmo que Streamlit Sharing esteja aberto

# Normas/referências (configurável)
# *Não é “diagnóstico”; é comparação automatizada com faixas de referência configuráveis.*
DEFAULT_NORMS = {
    "pain": {"low": [0, 3], "moderate": [4, 6], "high": [7, 10]},
    "strength": {"low": [0, 3], "moderate": [4, 6], "good": [7, 10]},
    "mobility": {"low": [0, 3], "moderate": [4, 6], "good": [7, 10]},
    "conditioning_index": {"poor": [0, 39], "average": [40, 69], "good": [70, 100]},
    "risk_score": {"low": [0, 29], "moderate": [30, 59], "high": [60, 100]},
}

# =========================
# HELPERS
# =========================
def supabase() -> Client:
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE:
        st.error("Secrets do Supabase não configurados. Configure SUPABASE_URL e SUPABASE_SERVICE_ROLE.")
        st.stop()
    return create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE)

def calc_age(birth_date: date | None) -> int | None:
    if not birth_date:
        return None
    return relativedelta(date.today(), birth_date).years

def bucket_label(value: float | int | None, buckets: dict) -> str:
    if value is None:
        return "não informado"
    for name, rng in buckets.items():
        lo, hi = rng
        if lo <= value <= hi:
            return name
    return "fora da faixa"

def safe_int(x):
    try:
        if x is None or x == "":
            return None
        return int(x)
    except:
        return None

def safe_float(x):
    try:
        if x is None or x == "":
            return None
        return float(x)
    except:
        return None

def compute_conditioning_index(cardio: dict, motor: dict, plyo: dict) -> float | None:
    """
    Índice 0-100 baseado no que estiver preenchido.
    """
    scores = []
    # cardio
    if cardio:
        vo2 = safe_float(cardio.get("vo2_est"))
        hrrec = safe_float(cardio.get("hr_recovery_1min"))
        if vo2 is not None:
            scores.append(min(100, max(0, (vo2 / 60) * 100)))  # heurística
        if hrrec is not None:
            scores.append(min(100, max(0, (hrrec / 40) * 100)))  # heurística
    # motor control
    if motor:
        mscore = safe_float(motor.get("motor_control_score"))
        if mscore is not None:
            scores.append(min(100, max(0, mscore)))
    # plyo
    if plyo:
        rsi = safe_float(plyo.get("rsi"))
        if rsi is not None:
            scores.append(min(100, max(0, (rsi / 3.0) * 100)))  # heurística

    if not scores:
        return None
    return round(sum(scores) / len(scores), 1)

def compute_risk_score(pain, mobility, strength, combined: dict, posture: dict, plyo: dict, motor: dict) -> float | None:
    """
    Escore 0-100 (quanto maior, maior risco).
    Só usa o que estiver preenchido.
    """
    parts = []

    # Dor
    if pain is not None:
        parts.append((pain / 10) * 30)  # até 30 pts

    # Mobilidade/força baixos aumentam risco
    if mobility is not None:
        parts.append(((10 - mobility) / 10) * 20)  # até 20
    if strength is not None:
        parts.append(((10 - strength) / 10) * 20)  # até 20

    # Movimentos combinados: se indicar dor em combos, aumenta
    if combined:
        flags = combined.get("pain_triggers", [])
        if isinstance(flags, list) and len(flags) > 0:
            parts.append(min(20, 5 * len(flags)))  # até 20

    # Postura/RPG: se marcou desequilíbrios, aumenta
    if posture:
        imbalances = posture.get("imbalances", [])
        if isinstance(imbalances, list) and len(imbalances) > 0:
            parts.append(min(15, 3 * len(imbalances)))  # até 15 (mas vai somar, depois clamp)

    # Pliometria: se RSI muito baixo ou assimetria alta
    if plyo:
        asym = safe_float(plyo.get("asymmetry_pct"))
        if asym is not None and asym >= 10:
            parts.append(min(20, (asym / 30) * 20))

    # Controle motor baixo
    if motor:
        mscore = safe_float(motor.get("motor_control_score"))
        if mscore is not None and mscore < 60:
            parts.append(min(15, ((60 - mscore) / 60) * 15))

    if not parts:
        return None
    return round(min(100, sum(parts)), 1)

def compute_muscle_mass_index(joint_muscle: dict) -> float | None:
    """
    IM muscular (campo/estimativa) – se tiver.
    """
    if not joint_muscle:
        return None
    val = safe_float(joint_muscle.get("muscle_mass_index"))
    if val is None:
        return None
    return round(val, 2)

def generate_report_pdf(patient: dict, assessment: dict, comparison: dict | None = None) -> bytes:
    """
    Gera PDF mesmo com campos em branco.
    """
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    w, h = A4

    def line(y, text, size=11, bold=False):
        c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        c.drawString(2*cm, y, str(text)[:120])

    y = h - 2*cm
    line(y, "RTP PRO – Relatório de Avaliação Funcional", 14, True); y -= 0.8*cm
    line(y, f"Profissional: {APP_SUBTITLE}", 11); y -= 0.6*cm
    line(y, f"Data: {assessment.get('assessment_date', '')}  |  Tipo: {assessment.get('assessment_type','')}", 11); y -= 0.8*cm

    line(y, f"Paciente: {patient.get('full_name','')}", 12, True); y -= 0.6*cm
    line(y, f"Nascimento: {patient.get('birth_date','')}  |  Idade: {calc_age(patient.get('birth_date'))}", 10); y -= 0.6*cm

    pain = assessment.get("pain_level")
    mobility = assessment.get("mobility")
    strength = assessment.get("strength")
    conditioning = assessment.get("conditioning_index")
    mmi = assessment.get("muscle_mass_index")
    risk = assessment.get("risk_score")

    y -= 0.2*cm
    line(y, "Resumo e Índices", 12, True); y -= 0.6*cm
    line(y, f"Dor: {pain if pain is not None else '—'} ({bucket_label(pain, DEFAULT_NORMS['pain'])})", 10); y -= 0.45*cm
    line(y, f"Mobilidade: {mobility if mobility is not None else '—'} ({bucket_label(mobility, DEFAULT_NORMS['mobility'])})", 10); y -= 0.45*cm
    line(y, f"Força: {strength if strength is not None else '—'} ({bucket_label(strength, DEFAULT_NORMS['strength'])})", 10); y -= 0.45*cm
    line(y, f"Índice de Condicionamento Físico: {conditioning if conditioning is not None else '—'} ({bucket_label(conditioning, DEFAULT_NORMS['conditioning_index'])})", 10); y -= 0.45*cm
    line(y, f"Índice de Massa Muscular: {mmi if mmi is not None else '—'}", 10); y -= 0.45*cm
    line(y, f"Risco de Lesão/Recidiva: {risk if risk is not None else '—'} ({bucket_label(risk, DEFAULT_NORMS['risk_score'])})", 10); y -= 0.7*cm

    obs = assessment.get("observations") or ""
    line(y, "Observações", 12, True); y -= 0.6*cm
    for chunk in [obs[i:i+95] for i in range(0, len(obs), 95)]:
        line(y, chunk, 10); y -= 0.45*cm
        if y < 3*cm:
            c.showPage()
            y = h - 2*cm

    # Comparação (se existir)
    if comparison:
        if y < 6*cm:
            c.showPage(); y = h - 2*cm
        y -= 0.2*cm
        line(y, "Comparação com avaliação anterior", 12, True); y -= 0.6*cm
        for k, v in comparison.items():
            line(y, f"{k}: {v}", 10); y -= 0.45*cm
            if y < 3*cm:
                c.showPage(); y = h - 2*cm

    c.showPage()
    c.save()
    return buf.getvalue()

def require_login():
    if not REQUIRE_AUTH:
        return
    if not APP_PASSWORD:
        st.warning("APP_PASSWORD não definido no Secrets. Defina para manter privado.")
        return

    if st.session_state.get("authed") is True:
        return

    st.title(APP_TITLE)
    st.caption("Acesso restrito")
    pwd = st.text_input("Senha do aplicativo", type="password")
    if st.button("Entrar"):
        if pwd == APP_PASSWORD:
            st.session_state["authed"] = True
            st.success("Acesso liberado.")
            st.rerun()
        else:
            st.error("Senha incorreta.")
    st.stop()


# =========================
# DB ACTIONS
# =========================
def db_get_patients(q: str = ""):
    sb = supabase()
    if q:
        res = sb.table("patients").select("*").ilike("full_name", f"%{q}%").order("full_name").execute()
    else:
        res = sb.table("patients").select("*").order("full_name").limit(50).execute()
    return res.data or []

def db_create_patient(payload: dict):
    sb = supabase()
    res = sb.table("patients").insert(payload).execute()
    return (res.data or [None])[0]

def db_create_episode(payload: dict):
    sb = supabase()
    res = sb.table("episodes").insert(payload).execute()
    return (res.data or [None])[0]

def db_get_open_episode(patient_id: str):
    sb = supabase()
    res = sb.table("episodes").select("*").eq("patient_id", patient_id).eq("status", "open").order("created_at", desc=True).limit(1).execute()
    data = res.data or []
    return data[0] if data else None

def db_list_assessments(patient_id: str):
    sb = supabase()
    res = sb.table("assessments").select("*").eq("patient_id", patient_id).order("assessment_date", desc=True).execute()
    return res.data or []

def db_insert_assessment(payload: dict):
    sb = supabase()
    res = sb.table("assessments").insert(payload).execute()
    return (res.data or [None])[0]

def db_upload_photo(assessment_id: str, photo_type: str, file, notes: str = ""):
    sb = supabase()
    # Upload to Storage
    ext = "jpg"
    name = getattr(file, "name", "") or "photo.jpg"
    if "." in name:
        ext = name.split(".")[-1].lower()
    path = f"{assessment_id}/{photo_type}_{int(datetime.utcnow().timestamp())}.{ext}"

    data = file.read()
    sb.storage.from_("assessment-photos").upload(path, data, {"content-type": file.type if hasattr(file, "type") else "image/jpeg"})

    # Store reference in DB
    row = {
        "assessment_id": assessment_id,
        "photo_type": photo_type,
        "storage_path": path,
        "notes": notes
    }
    sb.table("assessment_photos").insert(row).execute()
    return path

def db_get_last_assessment(patient_id: str, assessment_type: str, exclude_id: str | None = None):
    sb = supabase()
    q = sb.table("assessments").select("*").eq("patient_id", patient_id).eq("assessment_type", assessment_type).order("assessment_date", desc=True).limit(5)
    res = q.execute()
    items = res.data or []
    for it in items:
        if exclude_id and it["id"] == exclude_id:
            continue
        return it
    return None


# =========================
# UI SECTIONS
# =========================
def section_patient_picker():
    st.sidebar.header("👤 Paciente")
    q = st.sidebar.text_input("Buscar paciente (nome)", value="")
    pts = db_get_patients(q)

    if not pts:
        st.sidebar.info("Nenhum paciente encontrado.")
        chosen = None
    else:
        labels = [f"{p['full_name']} — {p['id'][:8]}" for p in pts]
        idx = st.sidebar.selectbox("Selecione", list(range(len(labels))), format_func=lambda i: labels[i])
        chosen = pts[idx]

    with st.sidebar.expander("➕ Cadastrar novo paciente", expanded=False):
        name = st.text_input("Nome completo")
        birth = st.date_input("Data de nascimento", value=None)
        sex = st.selectbox("Sexo", ["", "M", "F", "Outro"])
        phone = st.text_input("Telefone")
        email = st.text_input("E-mail")
        notes = st.text_area("Observações do paciente")
        if st.button("Salvar paciente"):
            if not name.strip():
                st.error("Informe o nome.")
            else:
                payload = {
                    "full_name": name.strip(),
                    "birth_date": birth.isoformat() if birth else None,
                    "sex": sex or None,
                    "phone": phone or None,
                    "email": email or None,
                    "notes": notes or None
                }
                p = db_create_patient(payload)
                st.success("Paciente criado.")
                st.session_state["patient_id"] = p["id"]
                st.rerun()

    if chosen:
        st.session_state["patient_id"] = chosen["id"]
    return chosen

def section_assessment_selector():
    st.sidebar.header("🧭 Menu")
    menu = st.sidebar.radio(
        "Escolha",
        ["Nova avaliação", "Histórico", "Comparação", "Relatórios"],
        index=0
    )

    st.sidebar.header("🧪 Escolha a avaliação")
    assessment_type = st.sidebar.selectbox(
        "Tipo",
        ["Avaliação Rápida", "Avaliação Completa"],
        index=0
    )
    st.session_state["assessment_type"] = "quick" if assessment_type == "Avaliação Rápida" else "full"
    return menu, st.session_state["assessment_type"]

def form_quick():
    st.subheader("⚡ Avaliação Rápida")
    col1, col2 = st.columns([2, 1], vertical_alignment="top")
    with col1:
        name = st.text_input("Nome do paciente (apenas para conferência no relatório)", value="")
        pain = st.slider("Nível de dor (0-10)", 0, 10, 5)
        strength = st.slider("Força muscular (0-10)", 0, 10, 5)
        obs = st.text_area("Observações", height=120)
    with col2:
        st.info("Rápida = triagem + índices + relatório. Você pode anexar fotos e testes rápidos abaixo.")

    # Blocos rápidos (inclui biomecânica por foto, controle motor, pliometria, cardio)
    with st.expander("📸 Biomecânica por fotos (rápido)", expanded=True):
        posture_front = st.file_uploader("Foto postura (frente)", type=["jpg", "jpeg", "png"], key="q_posture_front")
        posture_side = st.file_uploader("Foto postura (perfil)", type=["jpg", "jpeg", "png"], key="q_posture_side")
        facial = st.file_uploader("Foto facial (se aplicável)", type=["jpg", "jpeg", "png"], key="q_facial")
        photo_notes = st.text_area("Notas das fotos", key="q_photo_notes")

    with st.expander("🧠 Controle motor (rápido)", expanded=False):
        mc_score = st.slider("Score controle motor (0-100)", 0, 100, 70)
        mc_notes = st.text_area("Observações controle motor", key="q_mc_notes")

    with st.expander("🦘 Pliometria (rápido)", expanded=False):
        jump_cm = st.number_input("Salto vertical (cm)", min_value=0.0, step=0.5, value=0.0)
        rsi = st.number_input("RSI (Reactive Strength Index)", min_value=0.0, step=0.1, value=0.0)
        asym = st.number_input("Assimetria (%)", min_value=0.0, step=0.5, value=0.0)

    with st.expander("❤️ Cardiovascular (rápido)", expanded=False):
        vo2_est = st.number_input("VO2 estimado (ml/kg/min)", min_value=0.0, step=0.5, value=0.0)
        hr_rest = st.number_input("FC repouso", min_value=0.0, step=1.0, value=0.0)
        hr_rec = st.number_input("Recuperação FC 1min (bpm)", min_value=0.0, step=1.0, value=0.0)

    # Exames (rápido) – campos, não “prescrição”
    with st.expander("🧪 Exames laboratoriais (rápido)", expanded=False):
        labs = {
            "cpk": st.text_input("CPK (se tiver)"),
            "crp": st.text_input("PCR/CRP"),
            "esr": st.text_input("VHS/ESR"),
            "rf": st.text_input("Fator reumatoide (RF)"),
            "anti_ccp": st.text_input("Anti-CCP"),
            "vit_d": st.text_input("Vitamina D"),
            "notes": st.text_area("Notas de exames", height=80),
        }

    return {
        "display_name": name,
        "pain": pain,
        "mobility": None,
        "strength": strength,
        "observations": obs,
        "photos": {
            "posture_front": posture_front,
            "posture_side": posture_side,
            "facial": facial,
            "notes": photo_notes,
        },
        "motor_control": {"motor_control_score": mc_score, "notes": mc_notes},
        "plyometrics": {"jump_cm": jump_cm, "rsi": rsi, "asymmetry_pct": asym},
        "cardiovascular": {"vo2_est": vo2_est, "hr_rest": hr_rest, "hr_recovery_1min": hr_rec},
        "labs": labs,
    }

def form_full():
    st.subheader("📋 Avaliação Completa")
    st.caption("Organizada por seções: dor/queixa, postural (RPG/cadeias), movimentos combinados (causa da dor), biomecânica por fotos, músculo-articular, cardiovascular, controle motor universal, pliometria e exames.")

    top1, top2 = st.columns([2, 1], vertical_alignment="top")
    with top1:
        name = st.text_input("Nome do paciente (apenas para conferência no relatório)", value="")
        age = st.number_input("Idade", min_value=0, max_value=120, value=30)
        pathology = st.text_input("Patologia principal")
        chief = st.text_input("Queixa principal")
        pain = st.slider("Nível de dor (0-10)", 0, 10, 5)
        mobility = st.slider("Mobilidade (0-10)", 0, 10, 5)
        strength = st.slider("Força muscular (0-10)", 0, 10, 5)
        obs = st.text_area("Observações clínicas", height=120)
    with top2:
        st.info("A avaliação completa habilita comparação, índices e relatório profissional, mesmo com campos em branco.")

    with st.expander("🧭 Avaliação Postural (RPG / Cadeias Musculares)", expanded=True):
        chain = st.multiselect(
            "Cadeias com suspeita de encurtamento / tensão",
            ["Cadeia posterior", "Cadeia anterior", "Cadeia inspiratória", "Cadeias cruzadas", "Cadeia lateral"],
        )
        imbalances = st.multiselect(
            "Pontos de desequilíbrio (marque o que observar)",
            ["Anteversão pélvica", "Retroversão pélvica", "Hipercifose", "Hiperlordose", "Escoliose", "Valgo joelho", "Varo joelho", "Pé pronado", "Pé supinado", "Ombro anteriorizado", "Cabeça anteriorizada"]
        )
        rpg_notes = st.text_area("Notas (método RPG / postura)", height=90)
        posture_rpg = {"chains": chain, "imbalances": imbalances, "notes": rpg_notes}

    with st.expander("🧩 Causa da Dor – Movimentos Combinados (rastreamento)", expanded=True):
        triggers = st.multiselect(
            "Movimentos/combinações que provocam dor",
            ["Flexão + rotação", "Extensão + rotação", "Abdução + rotação", "Agachamento + rotação", "Elevação braço + rotação", "Marcha/corrida", "Saltos", "Apoio unilateral", "Subir escadas"]
        )
        region = st.multiselect(
            "Regiões suspeitas de origem (hipótese clínica)",
            ["Coluna cervical", "Coluna torácica", "Coluna lombar", "Quadril", "Joelho", "Tornozelo/pé", "Ombro", "Cotovelo", "Punho/mão", "ATM"]
        )
        combo_notes = st.text_area("Notas de testes combinados e hipótese de origem", height=90)
        combined = {"pain_triggers": triggers, "suspected_origin_regions": region, "notes": combo_notes}

    with st.expander("📸 Biomecânica por Fotos (postura / marcha / articular / facial)", expanded=True):
        posture_front = st.file_uploader("Foto postura (frente)", type=["jpg", "jpeg", "png"], key="f_posture_front")
        posture_side = st.file_uploader("Foto postura (perfil)", type=["jpg", "jpeg", "png"], key="f_posture_side")
        gait = st.file_uploader("Foto/vídeo (marcha) – se usar imagem, envie frame", type=["jpg", "jpeg", "png"], key="f_gait")
        joint = st.file_uploader("Foto articular específica", type=["jpg", "jpeg", "png"], key="f_joint")
        facial = st.file_uploader("Foto facial", type=["jpg", "jpeg", "png"], key="f_facial")
        bio_notes = st.text_area("Notas biomecânicas (observação)", height=90)
        biomechanics = {"notes": bio_notes}

    with st.expander("🦴 Avaliação Muscular / Articular / Funcional", expanded=False):
        rom = st.text_area("ADM / ROM (descrição)", height=90)
        strength_map = st.text_area("Força segmentar (ex.: glúteo médio, manguito, etc.)", height=90)
        functional_tests = st.multiselect(
            "Testes funcionais realizados",
            ["Y-Balance", "Single Leg Squat", "Step Down", "Hop Test", "Agachamento", "Prancha", "Ponte", "Lunge", "Overhead Squat"]
        )
        joint_muscle = {
            "rom": rom,
            "strength_map": strength_map,
            "functional_tests": functional_tests,
            "muscle_mass_index": st.text_input("Índice de massa muscular (atual) – se tiver"),
            "muscle_mass_expected": st.text_input("Índice de massa muscular (esperado) – se usar referência"),
        }

    with st.expander("🧠 Controle Motor Universal (focado)", expanded=False):
        mc_score = st.slider("Score controle motor (0-100)", 0, 100, 70)
        mc_deficits = st.multiselect(
            "Déficits observados",
            ["Estabilidade lombo-pélvica", "Controle escápulo-umeral", "Propriocepção tornozelo", "Controle valgo dinâmico", "Coordenação", "Tempo de reação"]
        )
        mc_notes = st.text_area("Notas controle motor", height=90)
        motor_control = {"motor_control_score": mc_score, "deficits": mc_deficits, "notes": mc_notes}

    with st.expander("🦘 Pliometria (completa)", expanded=False):
        jump_cm = st.number_input("Salto vertical (cm)", min_value=0.0, step=0.5, value=0.0, key="f_jump")
        rsi = st.number_input("RSI", min_value=0.0, step=0.1, value=0.0, key="f_rsi")
        asym = st.number_input("Assimetria (%)", min_value=0.0, step=0.5, value=0.0, key="f_asym")
        plyo_notes = st.text_area("Notas pliometria", height=80)
        plyo = {"jump_cm": jump_cm, "rsi": rsi, "asymmetry_pct": asym, "notes": plyo_notes}

    with st.expander("❤️ Cardiovascular (completa)", expanded=False):
        vo2_est = st.number_input("VO2 estimado", min_value=0.0, step=0.5, value=0.0, key="f_vo2")
        hr_rest = st.number_input("FC repouso", min_value=0.0, step=1.0, value=0.0, key="f_hrrest")
        hr_rec = st.number_input("Recuperação FC 1min", min_value=0.0, step=1.0, value=0.0, key="f_hrrec")
        cardio_notes = st.text_area("Notas cardio", height=80)
        cardio = {"vo2_est": vo2_est, "hr_rest": hr_rest, "hr_recovery_1min": hr_rec, "notes": cardio_notes}

    with st.expander("🧪 Exames laboratoriais (muscular / articular / reumato / inflamatório)", expanded=False):
        labs = {
            "cpk": st.text_input("CPK"),
            "crp": st.text_input("PCR/CRP"),
            "esr": st.text_input("VHS/ESR"),
            "rf": st.text_input("Fator reumatoide (RF)"),
            "anti_ccp": st.text_input("Anti-CCP"),
            "ana": st.text_input("FAN/ANA"),
            "uric_acid": st.text_input("Ácido úrico"),
            "vit_d": st.text_input("Vitamina D"),
            "notes": st.text_area("Notas de exames", height=80),
        }

    with st.expander("🙂 Avaliação Facial (se aplicável)", expanded=False):
        facial_notes = st.text_area("Observações faciais (simetria, dor, tensão, etc.)", height=90)
        facial_json = {"notes": facial_notes}

    photos = {
        "posture_front": posture_front,
        "posture_side": posture_side,
        "gait": gait,
        "joint": joint,
        "facial": facial,
    }

    return {
        "display_name": name,
        "age": age,
        "pathology": pathology,
        "chief": chief,
        "pain": pain,
        "mobility": mobility,
        "strength": strength,
        "observations": obs,
        "posture_rpg": posture_rpg,
        "combined": combined,
        "biomechanics": biomechanics,
        "photos": photos,
        "joint_muscle": joint_muscle,
        "motor_control": motor_control,
        "plyometrics": plyo,
        "cardiovascular": cardio,
        "labs": labs,
        "facial": facial_json,
    }

def build_comparison(prev: dict, current: dict) -> dict:
    out = {}
    def delta(field, label):
        a = prev.get(field)
        b = current.get(field)
        if a is None or b is None:
            return
        out[label] = f"{a} → {b} ({'melhora' if b < a and field=='pain_level' else 'variação'})"

    delta("pain_level", "Dor")
    delta("mobility", "Mobilidade")
    delta("strength", "Força")
    delta("conditioning_index", "Condicionamento")
    delta("risk_score", "Risco")

    return out

def save_assessment(patient: dict, assessment_type: str, data: dict):
    # episode
    ep = db_get_open_episode(patient["id"])
    if not ep:
        ep = db_create_episode({
            "patient_id": patient["id"],
            "chief_complaint": data.get("chief") or None,
            "main_pathology": data.get("pathology") or None
        })

    # compute indices
    pain = data.get("pain")
    mobility = data.get("mobility")
    strength = data.get("strength")
    cardio = data.get("cardiovascular") or {}
    motor = data.get("motor_control") or {}
    plyo = data.get("plyometrics") or {}

    conditioning_index = compute_conditioning_index(cardio, motor, plyo)
    muscle_mass_index = compute_muscle_mass_index(data.get("joint_muscle") or {})
    risk_score = compute_risk_score(pain, mobility, strength, data.get("combined") or {}, data.get("posture_rpg") or {}, plyo, motor)

    payload = {
        "patient_id": patient["id"],
        "episode_id": ep["id"],
        "assessment_type": assessment_type,
        "assessment_date": date.today().isoformat(),
        "pain_level": safe_int(pain),
        "mobility": safe_int(mobility),
        "strength": safe_int(strength),
        "observations": data.get("observations") or None,
        "conditioning_index": conditioning_index,
        "muscle_mass_index": muscle_mass_index,
        "risk_score": risk_score,
        "biomechanics": data.get("biomechanics") or None,
        "posture_rpg": data.get("posture_rpg") or None,
        "combined_movements": data.get("combined") or None,
        "cardiovascular": data.get("cardiovascular") or None,
        "motor_control": data.get("motor_control") or None,
        "plyometrics": data.get("plyometrics") or None,
        "labs": data.get("labs") or None,
        "facial": data.get("facial") or None,
        "joint_muscle": data.get("joint_muscle") or None,
        "report_summary": None,
    }

    saved = db_insert_assessment(payload)

    # upload photos (if any)
    photos = data.get("photos") or {}
    for ptype, file in photos.items():
        if file is not None:
            notes = ""
            if "notes" in photos:
                notes = photos.get("notes") or ""
            db_upload_photo(saved["id"], ptype, file, notes=notes)

    # compare with previous
    prev = db_get_last_assessment(patient["id"], assessment_type, exclude_id=saved["id"])
    comparison = build_comparison(prev, saved) if prev else None

    # generate pdf
    pdf = generate_report_pdf(patient, saved, comparison)

    return saved, pdf


# =========================
# MAIN
# =========================
require_login()

st.title(APP_TITLE)
st.caption(APP_SUBTITLE)

patient = section_patient_picker()
menu, assessment_type = section_assessment_selector()

if not patient:
    st.info("Selecione ou cadastre um paciente na barra lateral.")
    st.stop()

if menu == "Nova avaliação":
    st.divider()
    if assessment_type == "quick":
        data = form_quick()
        btn = st.button("💾 Salvar avaliação rápida", use_container_width=True)
    else:
        data = form_full()
        btn = st.button("💾 Salvar avaliação completa", use_container_width=True)

    if btn:
        saved, pdf = save_assessment(patient, assessment_type, data)
        st.success("Avaliação salva com sucesso.")
        st.download_button(
            "📄 Baixar relatório PDF",
            data=pdf,
            file_name=f"RTPPRO_{patient['full_name']}_{saved['assessment_date']}_{assessment_type}.pdf",
            mime="application/pdf"
        )

        st.subheader("📊 Resultado Profissional (automático)")
        st.write({
            "Dor": saved.get("pain_level"),
            "Mobilidade": saved.get("mobility"),
            "Força": saved.get("strength"),
            "Índice de Condicionamento": saved.get("conditioning_index"),
            "Índice de Massa Muscular": saved.get("muscle_mass_index"),
            "Risco (lesão/recidiva)": saved.get("risk_score"),
        })

elif menu == "Histórico":
    st.divider()
    st.subheader("📚 Histórico do paciente")
    items = db_list_assessments(patient["id"])
    if not items:
        st.info("Sem avaliações ainda.")
    else:
        df = pd.DataFrame(items)
        show_cols = ["assessment_date", "assessment_type", "pain_level", "mobility", "strength", "conditioning_index", "risk_score", "created_at"]
        show_cols = [c for c in show_cols if c in df.columns]
        st.dataframe(df[show_cols], use_container_width=True)

elif menu == "Comparação":
    st.divider()
    st.subheader("📈 Comparação de evolução")
    items = db_list_assessments(patient["id"])
    if len(items) < 2:
        st.info("Você precisa de pelo menos 2 avaliações para comparar.")
    else:
        # pick type
        t = st.selectbox("Tipo", ["quick", "full"], format_func=lambda x: "Avaliação Rápida" if x=="quick" else "Avaliação Completa")
        typed = [x for x in items if x["assessment_type"] == t]
        if len(typed) < 2:
            st.info("Sem 2 avaliações desse tipo ainda.")
        else:
            a = typed[0]
            b = typed[1]
            comp = build_comparison(b, a)
            st.write("Última vs anterior:")
            st.json(comp)

elif menu == "Relatórios":
    st.divider()
    st.subheader("🧾 Relatórios")
    items = db_list_assessments(patient["id"])
    if not items:
        st.info("Sem avaliações ainda.")
    else:
        labels = [f"{x['assessment_date']} | {x['assessment_type']} | {x['id'][:8]}" for x in items]
        idx = st.selectbox("Escolha uma avaliação para gerar PDF novamente", list(range(len(labels))), format_func=lambda i: labels[i])
        chosen = items[idx]
        prev = db_get_last_assessment(patient["id"], chosen["assessment_type"], exclude_id=chosen["id"])
        comp = build_comparison(prev, chosen) if prev else None
        pdf = generate_report_pdf(patient, chosen, comp)
        st.download_button(
            "📄 Baixar PDF",
            data=pdf,
            file_name=f"RTPPRO_{patient['full_name']}_{chosen['assessment_date']}_{chosen['assessment_type']}.pdf",
            mime="application/pdf"
        )
