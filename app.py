import json
from datetime import datetime, date

import numpy as np
import pandas as pd
import streamlit as st
from supabase import create_client

# =========================
# CONFIG
# =========================
st.set_page_config(page_title="RTP PRO – Avaliação Completa (Consultório)", layout="wide")

def clamp(x, a=0, b=100):
    return max(a, min(b, x))

# =========================
# SUPABASE
# =========================
SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_SERVICE_ROLE = st.secrets["SUPABASE_SERVICE_ROLE"]
supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE)

# =========================
# REFERÊNCIAS (EDITÁVEIS)
# =========================
DEFAULT_LAB_REFS = {
    # Inflamação / reumato / lesão
    "CRP_mgL":    {"low": 0.0, "high": 5.0,   "label": "PCR/CRP (mg/L)"},
    "ESR_mmH":    {"low": 0.0, "high": 20.0,  "label": "VHS/ESR (mm/h)"},
    "CK_U_L":     {"low": 0.0, "high": 190.0, "label": "CK/CPK (U/L)"},
    "URIC_mg_dL": {"low": 3.0, "high": 7.0,   "label": "Ácido úrico (mg/dL)"},
    "VITD_ng_mL": {"low": 30.0,"high": 100.0, "label": "Vitamina D (ng/mL)"},
    # Metabólico / recuperação / risco geral
    "A1C_pct":    {"low": 4.0, "high": 5.6,   "label": "HbA1c (%)"},
    "FERR_ng_mL": {"low": 30.0,"high": 300.0, "label": "Ferritina (ng/mL)"},
    "TSH_uIU_mL": {"low": 0.4, "high": 4.0,   "label": "TSH (uIU/mL)"},
    "B12_pg_mL":  {"low": 200.0,"high": 900.0,"label": "Vit B12 (pg/mL)"},
    "MG_mg_dL":   {"low": 1.7, "high": 2.2,   "label": "Magnésio (mg/dL)"},
    "CA_mg_dL":   {"low": 8.6, "high": 10.2,  "label": "Cálcio (mg/dL)"},
    # Hemograma simplificado (fadiga/recuperação)
    "HB_g_dL":    {"low": 12.0,"high": 17.5,  "label": "Hemoglobina (g/dL)"},
    # Reumato (qualitativo)
    "RF_pos":     {"label": "Fator reumatoide (positivo?)"},
    "ANTI_CCP_pos":{"label": "Anti-CCP (positivo?)"},
    "ANA_pos":    {"label": "FAN/ANA (positivo?)"},
}

# =========================
# HELPERS – MENSURAÇÕES
# =========================
def asym_pct(d, e):
    if d is None or e is None:
        return None
    d = float(d); e = float(e)
    m = max(d, e)
    if m == 0:
        return 0.0
    return abs(d - e) / m * 100.0

def sym_index_from_asym(asym_max):
    if asym_max is None:
        return None
    return clamp(100 - 5 * float(asym_max), 0, 100)

def ruffier_index(p0, p1, p2):
    p0 = float(p0); p1 = float(p1); p2 = float(p2)
    return ((p0 + p1 + p2) - 200.0) / 10.0

def conditioning_score_from_ruffier(ir):
    return clamp(100 - 12.5 * float(ir), 0, 100)

def vo2_queens(sex, hr_bpm):
    hr_bpm = float(hr_bpm)
    if sex == "Masculino":
        return 111.33 - 0.42 * hr_bpm
    return 65.81 - 0.1847 * hr_bpm

def vo2_score_simple(vo2):
    return clamp(((float(vo2) - 20) / (60 - 20)) * 100, 0, 100)

def contact_time_seconds(frames_contact, fps):
    frames_contact = float(frames_contact)
    fps = float(fps)
    if fps <= 0:
        return None
    return frames_contact / fps

def biomech_score(points_list):
    pts = [float(p) for p in points_list if p is not None]
    if not pts:
        return None
    n = len(pts)
    return clamp((sum(pts) / (3 * n)) * 100, 0, 100)

def pain_index(pains):
    vals = [float(x) for x in pains if x is not None]
    if not vals:
        return None, None, None
    avg = sum(vals) / len(vals)
    mx = max(vals)
    idx = clamp(100 - avg * 10, 0, 100)
    return avg, mx, idx

def rsi(height_cm, contact_s):
    if height_cm is None or contact_s is None:
        return None
    if float(contact_s) <= 0:
        return None
    return (float(height_cm) / 100.0) / float(contact_s)

def plyo_score_from_metrics(rsi_val, asym_val, hop_lsi):
    parts = []
    if rsi_val is not None:
        parts.append(clamp((float(rsi_val) / 3.0) * 100, 0, 100))
    if hop_lsi is not None:
        parts.append(clamp(((float(hop_lsi) - 70) / 30) * 100, 0, 100))
    if asym_val is not None:
        parts.append(clamp(100 - (float(asym_val) * 5), 0, 100))
    if not parts:
        return None
    return sum(parts) / len(parts)

# ---- CONTROLE MOTOR ----
def motor_control_score(items_0_3):
    vals = [float(x) for x in items_0_3 if x is not None]
    if not vals:
        return None
    n = len(vals)
    return clamp((sum(vals) / (3 * n)) * 100, 0, 100)

def motor_asym_score(d_val, e_val):
    if d_val is None or e_val is None:
        return None, None
    a = asym_pct(float(d_val), float(e_val))
    score = clamp(100 - (a * 2), 0, 100)
    return a, score

def motor_video_score(frames_comp, frames_total):
    frames_comp = float(frames_comp)
    frames_total = float(frames_total)
    if frames_total <= 0:
        return None
    ratio = frames_comp / frames_total
    return clamp(100 - (ratio * 100), 0, 100)

# ---- IMC ----
def calc_bmi(weight_kg, height_cm):
    if not weight_kg or not height_cm:
        return None
    h = float(height_cm) / 100.0
    if h <= 0:
        return None
    return float(weight_kg) / (h * h)

def bmi_category(bmi):
    if bmi is None:
        return "não informado"
    b = float(bmi)
    if b < 18.5:
        return "baixo peso"
    if b < 25:
        return "saudável"
    if b < 30:
        return "sobrepeso"
    if b < 35:
        return "obesidade I"
    if b < 40:
        return "obesidade II"
    return "obesidade III"

def bmi_risk_modifier(bmi):
    """
    Penalidade (0..15) para risco/recidiva.
    """
    if bmi is None:
        return 0
    cat = bmi_category(bmi)
    if cat == "saudável":
        return 0
    if cat == "sobrepeso":
        return 5
    if "obesidade" in cat:
        return 10
    if cat == "baixo peso":
        return 8
    return 0

# =========================
# EXAMES – CLASSIFICAÇÃO E SCORE
# =========================
def parse_float(x):
    try:
        if x is None:
            return None
        if isinstance(x, str) and x.strip() == "":
            return None
        return float(str(x).replace(",", "."))
    except:
        return None

def lab_status_numeric(value, low, high):
    """
    Retorna: ("normal"/"baixo"/"alto"/"não informado", delta_normalizado)
    delta_normalizado ~ quanto fora (0..1.5)
    """
    v = parse_float(value)
    if v is None:
        return "não informado", 0.0
    if low is not None and v < low:
        # distância relativa
        dn = (low - v) / max(1e-6, (high - low) if (high is not None and high > low) else low)
        return "baixo", float(clamp(dn * 100, 0, 150)) / 100.0
    if high is not None and v > high:
        dn = (v - high) / max(1e-6, (high - low) if (low is not None and high > low) else high)
        return "alto", float(clamp(dn * 100, 0, 150)) / 100.0
    return "normal", 0.0

def labs_index_and_flags(labs_dict, refs):
    """
    Gera:
      - labs_index (0–100)
      - flags (lista de alertas)
      - table (lista para dataframe)
    """
    flags = []
    table = []

    # pesos por relevância para lesão/recuperação (heurístico)
    weights = {
        "CRP_mgL": 18, "ESR_mmH": 10, "CK_U_L": 14,
        "VITD_ng_mL": 10, "A1C_pct": 8, "FERR_ng_mL": 6,
        "HB_g_dL": 6, "TSH_uIU_mL": 6, "URIC_mg_dL": 6,
        "B12_pg_mL": 4, "MG_mg_dL": 4, "CA_mg_dL": 4,
    }

    penalty = 0.0
    max_penalty = sum(weights.values()) + 20  # + qualitativos reumato

    # Numéricos
    for k, meta in refs.items():
        if k.endswith("_pos"):
            continue
        if k not in labs_dict:
            continue
        v = labs_dict.get(k)
        low = meta.get("low", None)
        high = meta.get("high", None)
        stt, dn = lab_status_numeric(v, low, high)
        w = weights.get(k, 3)
        penalty += w * dn

        label = meta.get("label", k)
        table.append({
            "Exame": label,
            "Valor": v if (v is not None and v != "") else "—",
            "Referência": f"{low}–{high}" if (low is not None and high is not None) else "—",
            "Status": stt
        })

        # Flags úteis (não diagnóstico)
        if k == "CRP_mgL" and stt == "alto":
            flags.append("Inflamação sistêmica elevada (PCR alta) → pode aumentar risco de recidiva/irritação tecidual.")
        if k == "ESR_mmH" and stt == "alto":
            flags.append("VHS alta → padrão inflamatório; correlacionar com dor/rigidez/fadiga.")
        if k == "CK_U_L" and stt == "alto":
            flags.append("CK/CPK alta → possível estresse/dano muscular recente; ajustar carga.")
        if k == "VITD_ng_mL" and stt == "baixo":
            flags.append("Vitamina D baixa → pode prejudicar recuperação muscular/óssea; considerar correção clínica.")
        if k == "A1C_pct" and stt == "alto":
            flags.append("HbA1c elevada → recuperação tecidual pode ser mais lenta; cuidado com progressão de carga.")
        if k == "HB_g_dL" and stt == "baixo":
            flags.append("Hemoglobina baixa → menor tolerância ao esforço; ajustar condicionamento.")
        if k == "URIC_mg_dL" and stt == "alto":
            flags.append("Ácido úrico alto → correlacionar com dor articular/crises; atenção em cargas.")
        if k == "TSH_uIU_mL" and (stt == "alto" or stt == "baixo"):
            flags.append("TSH fora da faixa → pode influenciar fadiga/força/recuperação.")

    # Reumato (qualitativos)
    rf = bool(labs_dict.get("RF_pos", False))
    accp = bool(labs_dict.get("ANTI_CCP_pos", False))
    ana = bool(labs_dict.get("ANA_pos", False))

    if rf:
        penalty += 10
        flags.append("RF positivo (triagem reumato) → correlacionar com dor articular/rigidez e exames inflamatórios.")
    if accp:
        penalty += 10
        flags.append("Anti-CCP positivo → maior suspeita inflamatória; correlacionar clinicamente.")
    if ana:
        penalty += 6
        flags.append("FAN/ANA positivo → marcador inespecífico; correlacionar com sintomas sistêmicos.")

    # Score 0–100
    labs_index = clamp(100 - (penalty / max_penalty) * 100, 0, 100)

    # Risk hints baseados em combos com dor e índice motor (sem diagnóstico)
    return float(labs_index), flags, table

# =========================
# RISCO/SAÚDE (FINAL)
# =========================
def health_index(cond_score, sym_idx, biomech, pain_idx, plyo_sc, motor_sc, labs_idx, bmi_mod):
    """
    Score final 0–100 (maior = melhor).
    bmi_mod: penalidade 0..15 (aumenta risco)
    """
    parts = []
    weights = {
        "cond": 0.18, "sym": 0.16, "bio": 0.12, "pain": 0.10,
        "plyo": 0.14, "motor": 0.15, "labs": 0.15
    }

    if cond_score is not None: parts.append(("cond", float(cond_score)))
    if sym_idx is not None:    parts.append(("sym", float(sym_idx)))
    if biomech is not None:    parts.append(("bio", float(biomech)))
    if pain_idx is not None:   parts.append(("pain", float(pain_idx)))
    if plyo_sc is not None:    parts.append(("plyo", float(plyo_sc)))
    if motor_sc is not None:   parts.append(("motor", float(motor_sc)))
    if labs_idx is not None:   parts.append(("labs", float(labs_idx)))

    wsum = sum(weights[k] for k, _ in parts) if parts else 0
    if wsum == 0:
        return None, None, None

    score = sum(weights[k] * v for k, v in parts) / wsum
    score = clamp(score - float(bmi_mod), 0, 100)  # IMC penaliza o score

    risk = clamp(100 - score, 0, 100)

    reinjury = None
    # recidiva baseada em simetria+plyo+motor+labs
    reinjury_parts = []
    if sym_idx is not None:  reinjury_parts.append((0.25, 100 - sym_idx))
    if plyo_sc is not None:  reinjury_parts.append((0.25, 100 - plyo_sc))
    if motor_sc is not None: reinjury_parts.append((0.25, 100 - motor_sc))
    if labs_idx is not None: reinjury_parts.append((0.25, 100 - labs_idx))
    if reinjury_parts:
        reinjury = clamp(sum(w * v for w, v in reinjury_parts) / sum(w for w, _ in reinjury_parts), 0, 100)
        reinjury = clamp(reinjury + (bmi_mod * 1.2), 0, 100)

    return float(score), float(risk), (float(reinjury) if reinjury is not None else None)

# =========================
# DB HELPERS
# =========================
def db_list_patients(search=""):
    q = supabase.table("patients").select("*").order("name", desc=False)
    if search:
        q = q.ilike("name", f"%{search}%")
    return q.execute().data or []

def db_create_patient(name, dob, phone):
    payload = {"name": name, "dob": str(dob) if dob else None, "phone": phone or None}
    return supabase.table("patients").insert(payload).execute().data[0]

def db_get_patient(patient_id):
    r = supabase.table("patients").select("*").eq("id", patient_id).limit(1).execute().data
    return r[0] if r else None

def db_insert_assessment(patient_id, eval_date_iso, data_dict):
    payload = {"patient_id": patient_id, "eval_date": eval_date_iso, "data": data_dict}
    return supabase.table("assessments").insert(payload).execute().data[0]

def db_list_assessments(patient_id):
    return (
        supabase.table("assessments")
        .select("*")
        .eq("patient_id", patient_id)
        .order("eval_date", desc=True)
        .execute()
        .data
        or []
    )

# =========================
# INIT SESSION DEFAULTS (evita NameError)
# =========================
defaults = {
    "sym_idx_runtime": None,
    "cond_score_runtime": None,
    "vo2_runtime": None,
    "vo2_score_runtime": None,
    "plyo_score_runtime": None,
    "bio_score_runtime": None,
    "posture_index_runtime": None,
    "posture_flags_runtime": {"cadeia_anterior": 0, "cadeia_posterior": 0, "cadeia_lateral": 0},
    "mc_final_runtime": None,
    "pain_index_runtime": None,
    "pain_avg_runtime": None,
    "pain_max_runtime": None,
    "labs_index_runtime": None,
    "labs_flags_runtime": [],
    "labs_table_runtime": [],
    "bmi_runtime": None,
    "bmi_cat_runtime": "não informado",
    "bmi_penalty_runtime": 0,
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

# =========================
# UI
# =========================
st.title("🧠 RTP PRO – Avaliação Completa (Consultório, sem aparelhos)")
st.caption("Relatório automático e comparação por consulta. Campos em branco não impedem salvar.")

with st.sidebar:
    st.header("👤 Paciente")
    search = st.text_input("Buscar paciente (nome)", "")
    patients = db_list_patients(search)

    patient_options = ["— Selecione —"] + [f"{p['name']} | {p['id']}" for p in patients]
    chosen = st.selectbox("Selecionar", patient_options, index=0)

    st.divider()
    st.subheader("➕ Cadastrar novo paciente")
    new_name = st.text_input("Nome completo", key="new_name")
    new_dob = st.date_input("Data de nascimento", value=None, key="new_dob")
    new_phone = st.text_input("Telefone", key="new_phone")
    if st.button("Cadastrar paciente", type="primary"):
        if not new_name.strip():
            st.error("Digite o nome.")
        else:
            p = db_create_patient(new_name.strip(), new_dob, new_phone.strip())
            st.success(f"Paciente cadastrado: {p['name']}")
            st.rerun()

    st.divider()
    st.subheader("⚙️ Referências de Exames (opcional)")
    st.caption("Se quiser, você pode ajustar as faixas. Se não mexer, o app usa o padrão.")
    if st.checkbox("Ajustar referências agora"):
        for key, meta in DEFAULT_LAB_REFS.items():
            if key.endswith("_pos"):
                continue
            c1, c2 = st.columns(2)
            low = c1.number_input(f"{meta['label']} – mínimo", value=float(meta["low"]), step=0.1, key=f"ref_low_{key}")
            high = c2.number_input(f"{meta['label']} – máximo", value=float(meta["high"]), step=0.1, key=f"ref_high_{key}")
            DEFAULT_LAB_REFS[key]["low"] = float(low)
            DEFAULT_LAB_REFS[key]["high"] = float(high)

patient_id = None
if chosen != "— Selecione —":
    patient_id = chosen.split("|")[-1].strip()

if not patient_id:
    st.info("Selecione um paciente na barra lateral.")
    st.stop()

patient = db_get_patient(patient_id)
st.subheader(f"👤 {patient['name']}  |  Nasc: {patient.get('dob','')}  |  Tel: {patient.get('phone','')}")

assessments = db_list_assessments(patient_id)
prev_assessment = assessments[1] if len(assessments) >= 2 else None

tabs = st.tabs([
    "1) Perimetria & Assimetria",
    "2) Cardiorrespiratória (Cond/VO₂)",
    "3) Pliometria",
    "4) Biomecânica (Vídeo)",
    "5) Postura (RPG)",
    "6) Controle Motor",
    "7) Dor + Movimentos (causa)",
    "8) IMC / Antropometria",
    "9) Exames de Sangue",
    "10) Comparação / Gráficos / Salvar"
])

# =========================
# TAB 1 – PERIMETRIA
# =========================
with tabs[0]:
    st.markdown("### Perimetria (cm) — Direita x Esquerda")
    segs = [
        "Coxa (10 cm acima patela)",
        "Panturrilha (maior perímetro)",
        "Braço (10 cm acima olécrano)",
        "Antebraço (maior perímetro)",
        "Glúteo (maior perímetro)"
    ]

    per_rows = []
    head = st.columns([3, 2, 2, 2])
    head[0].write("Segmento")
    head[1].write("Direita (cm)")
    head[2].write("Esquerda (cm)")
    head[3].write("Assimetria (%)")

    for s in segs:
        c = st.columns([3, 2, 2, 2])
        c[0].write(s)
        d = c[1].number_input(f"D {s}", min_value=0.0, step=0.1, key=f"per_d_{s}", label_visibility="collapsed")
        e = c[2].number_input(f"E {s}", min_value=0.0, step=0.1, key=f"per_e_{s}", label_visibility="collapsed")
        a = asym_pct(d, e)
        c[3].write(f"{a:.1f}%" if a is not None else "—")
        per_rows.append({"segment": s, "D_cm": d, "E_cm": e, "asym_pct": a})

    asym_values = [r["asym_pct"] for r in per_rows if r["asym_pct"] is not None]
    asym_max = max(asym_values) if asym_values else None
    sym_idx = sym_index_from_asym(asym_max) if asym_max is not None else None
    st.session_state["sym_idx_runtime"] = sym_idx

    if asym_max is not None:
        st.info(f"Pior assimetria: **{asym_max:.1f}%** | Índice de Simetria: **{sym_idx:.0f}/100**")
    else:
        st.warning("Se não medir perimetria, pode deixar em branco.")

# =========================
# TAB 2 – CARDIO
# =========================
with tabs[1]:
    st.markdown("### Cardiorrespiratória (simples)")
    sex = st.selectbox("Sexo", ["Masculino", "Feminino"], index=0, key="sex")
    age = st.number_input("Idade (anos)", min_value=0, step=1, key="age")
    weight = st.number_input("Peso (kg)", min_value=0.0, step=0.1, key="weight")

    st.divider()
    st.markdown("#### A) Ruffier (30 agachamentos / 45s)")
    p0 = st.number_input("P0 – FC repouso", min_value=0, step=1, key="p0")
    p1 = st.number_input("P1 – FC imediata", min_value=0, step=1, key="p1")
    p2 = st.number_input("P2 – FC 1 min", min_value=0, step=1, key="p2")

    ir = None
    cond_score = None
    if p0 > 0 and p1 > 0 and p2 > 0:
        ir = ruffier_index(p0, p1, p2)
        cond_score = conditioning_score_from_ruffier(ir)
        st.success(f"Índice Ruffier: **{ir:.2f}** | Condicionamento: **{cond_score:.0f}/100**")
    else:
        st.info("Se não fizer Ruffier, deixe em branco.")
    st.session_state["cond_score_runtime"] = cond_score

    st.divider()
    st.markdown("#### B) Queens Step (opcional) → VO₂")
    hr15 = st.number_input("FC por 15s após o teste", min_value=0, step=1, key="hr15")
    vo2 = None
    vo2_score = None
    if hr15 > 0:
        hr = hr15 * 4
        vo2 = vo2_queens(sex, hr)
        vo2_score = vo2_score_simple(vo2)
        st.success(f"VO₂: **{vo2:.1f}** | Score: **{vo2_score:.0f}/100**")
    st.session_state["vo2_runtime"] = vo2
    st.session_state["vo2_score_runtime"] = vo2_score

# =========================
# TAB 3 – PLIOMETRIA
# =========================
with tabs[2]:
    st.markdown("### Pliometria")
    cmj = st.number_input("Salto vertical (CMJ) cm", min_value=0.0, step=0.5, key="cmj")

    st.divider()
    hop_d = st.number_input("Hop Direito (cm)", min_value=0.0, step=1.0, key="hop_d")
    hop_e = st.number_input("Hop Esquerdo (cm)", min_value=0.0, step=1.0, key="hop_e")
    hop_asym = asym_pct(hop_d, hop_e) if (hop_d > 0 and hop_e > 0) else None
    hop_lsi = (min(hop_d, hop_e) / max(hop_d, hop_e) * 100) if (hop_d > 0 and hop_e > 0) else None
    if hop_lsi is not None:
        st.info(f"LSI: **{hop_lsi:.1f}%** | Assimetria: **{hop_asym:.1f}%**")

    st.divider()
    fps_p = st.selectbox("FPS do vídeo do salto (se usar)", [120, 240, 60], index=0, key="fps_plyo")
    frames_contact = st.number_input("Frames contato no salto (se medir)", min_value=0.0, step=1.0, key="frames_contact_plyo")
    contact_s = contact_time_seconds(frames_contact, fps_p) if frames_contact > 0 else None
    rsi_val = rsi(cmj, contact_s) if (cmj > 0 and contact_s is not None) else None
    if rsi_val is not None:
        st.success(f"Contato: **{contact_s:.3f}s** | RSI: **{rsi_val:.2f}**")

    plyo_sc = plyo_score_from_metrics(rsi_val, hop_asym, hop_lsi)
    st.session_state["plyo_score_runtime"] = plyo_sc
    if plyo_sc is not None:
        st.success(f"Índice Pliométrico: **{plyo_sc:.0f}/100**")
    else:
        st.info("Se não tiver dados pliométricos, pode deixar em branco.")

# =========================
# TAB 4 – BIOMECÂNICA
# =========================
with tabs[3]:
    st.markdown("### Biomecânica por vídeo (tempo de contato + checklist)")
    fps = st.selectbox("FPS do vídeo", [120, 240, 60], index=0, key="fps")
    frames_r = st.number_input("Frames contato – Pé Direito", min_value=0.0, step=1.0, key="frames_r")
    frames_l = st.number_input("Frames contato – Pé Esquerdo", min_value=0.0, step=1.0, key="frames_l")

    ct_r = contact_time_seconds(frames_r, fps) if frames_r > 0 else None
    ct_l = contact_time_seconds(frames_l, fps) if frames_l > 0 else None
    ct_asym = asym_pct(ct_r, ct_l) if (ct_r is not None and ct_l is not None) else None

    c1, c2, c3 = st.columns(3)
    c1.metric("Contato D (s)", f"{ct_r:.3f}" if ct_r else "—")
    c2.metric("Contato E (s)", f"{ct_l:.3f}" if ct_l else "—")
    c3.metric("Assimetria contato (%)", f"{ct_asym:.1f}%" if ct_asym else "—")

    st.divider()
    items = [
        "Controle de tronco",
        "Valgo dinâmico (joelho)",
        "Controle de quadril",
        "Estabilidade de tornozelo",
        "Simetria do apoio",
        "Coordenação geral"
    ]
    points = []
    flags = {"valgo_dinamico": False, "tronco_instavel": False, "prona_pes": False}
    for it in items:
        p = st.slider(it, 0, 3, 2, key=f"bio_{it}")
        points.append(p)

    if st.session_state.get("bio_Valgo dinâmico (joelho)", 2) <= 1:
        flags["valgo_dinamico"] = True
    if st.session_state.get("bio_Controle de tronco", 2) <= 1:
        flags["tronco_instavel"] = True
    if st.session_state.get("bio_Estabilidade de tornozelo", 2) <= 1:
        flags["prona_pes"] = True

    bio_score = biomech_score(points)
    st.session_state["bio_score_runtime"] = bio_score
    st.success(f"Biomecânica: **{bio_score:.0f}/100**")

# =========================
# TAB 5 – POSTURA (RPG)
# =========================
with tabs[4]:
    st.markdown("### Postura (RPG / Cadeias)")
    posture_items = [
        ("Cabeça anteriorizada", "cadeia_anterior"),
        ("Ombros protraídos", "cadeia_anterior"),
        ("Cifose aumentada", "cadeia_anterior"),
        ("Hiperlordose lombar", "cadeia_posterior"),
        ("Anteversão pélvica", "cadeia_anterior"),
        ("Retroversão pélvica", "cadeia_posterior"),
        ("Assimetria de ombros", "cadeia_lateral"),
        ("Assimetria de pelve", "cadeia_lateral"),
        ("Valgo de joelho", "cadeia_anterior"),
        ("Pronação de pé", "cadeia_anterior"),
    ]
    st.caption("0=ausente | 1=leve | 2=moderado | 3=importante")

    pvals = []
    chain_count = {"cadeia_anterior": 0, "cadeia_posterior": 0, "cadeia_lateral": 0}
    for label, chain in posture_items:
        v = st.slider(label, 0, 3, 1, key=f"post_{label}")
        pvals.append(v)
        if v >= 2:
            chain_count[chain] += 1

    severity = sum(pvals)
    max_sev = 3 * len(pvals)
    posture_index = clamp(100 - (severity / max_sev) * 100, 0, 100)
    st.session_state["posture_index_runtime"] = posture_index
    st.session_state["posture_flags_runtime"] = chain_count

    st.success(f"Índice Postural: **{posture_index:.0f}/100**")

# =========================
# TAB 6 – CONTROLE MOTOR
# =========================
with tabs[5]:
    st.markdown("### Controle Motor (sem aparelhos)")
    motor_items = [
        "Estabilidade lombo-pélvica",
        "Controle de valgo dinâmico",
        "Controle escápulo-umeral",
        "Propriocepção tornozelo",
        "Coordenação / dissociação",
        "Controle cervical (se aplicável)"
    ]
    motor_points = [st.slider(it, 0, 3, 2, key=f"mc_{it}") for it in motor_items]
    mc_score = motor_control_score(motor_points)

    st.divider()
    d_side = st.slider("Unilateral Direita (0–3)", 0, 3, 2, key="mc_d")
    e_side = st.slider("Unilateral Esquerda (0–3)", 0, 3, 2, key="mc_e")
    mc_asym, mc_asym_score = motor_asym_score(d_side, e_side)

    st.divider()
    frames_total = st.number_input("Frames analisados (vídeo opcional)", min_value=0.0, step=1.0, key="mc_frames_total")
    frames_comp = st.number_input("Frames com compensação", min_value=0.0, step=1.0, key="mc_frames_comp")
    mc_video = motor_video_score(frames_comp, frames_total) if frames_total > 0 else None

    parts = []
    if mc_score is not None: parts.append(mc_score)
    if mc_asym_score is not None: parts.append(mc_asym_score)
    if mc_video is not None: parts.append(mc_video)
    mc_final = float(sum(parts) / len(parts)) if parts else None
    st.session_state["mc_final_runtime"] = mc_final

    st.success(f"Controle Motor (final): **{mc_final:.0f}/100**" if mc_final is not None else "Preencha algum item para gerar score.")

# =========================
# TAB 7 – DOR + MOVIMENTOS
# =========================
with tabs[6]:
    st.markdown("### Dor (0–10) + Movimentos")
    base_moves = ["Flexão", "Extensão", "Inclinação Lateral D", "Inclinação Lateral E", "Rotação D", "Rotação E"]
    pains_list = []
    for m in base_moves:
        pains_list.append(st.slider(f"Dor na {m}", 0, 10, 0, key=f"pain_{m}"))

    avg_pain, max_pain, p_index = pain_index(pains_list)
    st.session_state["pain_avg_runtime"] = avg_pain
    st.session_state["pain_max_runtime"] = max_pain
    st.session_state["pain_index_runtime"] = p_index

    st.success(f"Dor média: **{avg_pain:.1f}** | Máx: **{max_pain:.0f}** | Índice Dor: **{p_index:.0f}/100**")

# =========================
# TAB 8 – IMC
# =========================
with tabs[7]:
    st.markdown("### IMC (automático)")
    st.caption("IMC entra no risco/recidiva automaticamente.")
    height_cm = st.number_input("Altura (cm)", min_value=0.0, step=0.5, key="height_cm")
    weight_kg = st.session_state.get("weight", None)

    bmi = calc_bmi(weight_kg, height_cm)
    cat = bmi_category(bmi)
    penalty = bmi_risk_modifier(bmi)

    st.session_state["bmi_runtime"] = bmi
    st.session_state["bmi_cat_runtime"] = cat
    st.session_state["bmi_penalty_runtime"] = penalty

    st.info(f"IMC: **{bmi:.1f}** | Categoria: **{cat}** | Penalidade risco: **{penalty}**" if bmi else "Preencha peso (na aba cardio) e altura.")

# =========================
# TAB 9 – EXAMES DE SANGUE
# =========================
with tabs[8]:
    st.markdown("### Exames de sangue (muscular / articular / facial / reumato)")
    st.caption("O app compara com referência e cruza com dor/controle motor/pliometria para estimar risco (não diagnóstico).")

    labs = {}
    c1, c2, c3 = st.columns(3)
    labs["CRP_mgL"] = c1.text_input("PCR/CRP (mg/L)", value="", key="lab_crp")
    labs["ESR_mmH"] = c2.text_input("VHS/ESR (mm/h)", value="", key="lab_esr")
    labs["CK_U_L"] = c3.text_input("CK/CPK (U/L)", value="", key="lab_ck")

    c4, c5, c6 = st.columns(3)
    labs["VITD_ng_mL"] = c4.text_input("Vitamina D (ng/mL)", value="", key="lab_vitd")
    labs["A1C_pct"] = c5.text_input("HbA1c (%)", value="", key="lab_a1c")
    labs["URIC_mg_dL"] = c6.text_input("Ácido úrico (mg/dL)", value="", key="lab_uric")

    c7, c8, c9 = st.columns(3)
    labs["FERR_ng_mL"] = c7.text_input("Ferritina (ng/mL)", value="", key="lab_ferr")
    labs["HB_g_dL"] = c8.text_input("Hemoglobina (g/dL)", value="", key="lab_hb")
    labs["TSH_uIU_mL"] = c9.text_input("TSH (uIU/mL)", value="", key="lab_tsh")

    c10, c11, c12 = st.columns(3)
    labs["B12_pg_mL"] = c10.text_input("Vit B12 (pg/mL)", value="", key="lab_b12")
    labs["MG_mg_dL"] = c11.text_input("Magnésio (mg/dL)", value="", key="lab_mg")
    labs["CA_mg_dL"] = c12.text_input("Cálcio (mg/dL)", value="", key="lab_ca")

    st.divider()
    st.markdown("#### Reumatológicos (marcar positivo)")
    r1, r2, r3 = st.columns(3)
    labs["RF_pos"] = r1.checkbox("RF positivo", value=False, key="lab_rf")
    labs["ANTI_CCP_pos"] = r2.checkbox("Anti-CCP positivo", value=False, key="lab_ccp")
    labs["ANA_pos"] = r3.checkbox("FAN/ANA positivo", value=False, key="lab_ana")

    labs_index, flags, table = labs_index_and_flags(labs, DEFAULT_LAB_REFS)
    st.session_state["labs_index_runtime"] = labs_index
    st.session_state["labs_flags_runtime"] = flags
    st.session_state["labs_table_runtime"] = table

    st.success(f"Índice Laboratorial: **{labs_index:.0f}/100**")
    if table:
        st.dataframe(pd.DataFrame(table), use_container_width=True)
    if flags:
        st.warning("Alertas automáticos:")
        for f in flags:
            st.write(f"- {f}")

# =========================
# TAB 10 – COMPARAÇÃO / SALVAR
# =========================
with tabs[9]:
    sym_idx = st.session_state.get("sym_idx_runtime")
    cond_score = st.session_state.get("cond_score_runtime")
    vo2 = st.session_state.get("vo2_runtime")
    vo2_score = st.session_state.get("vo2_score_runtime")
    plyo_sc = st.session_state.get("plyo_score_runtime")
    bio_score = st.session_state.get("bio_score_runtime")
    posture_index = st.session_state.get("posture_index_runtime")
    posture_flags = st.session_state.get("posture_flags_runtime")
    mc_final = st.session_state.get("mc_final_runtime")
    p_index = st.session_state.get("pain_index_runtime")
    avg_pain = st.session_state.get("pain_avg_runtime")
    max_pain = st.session_state.get("pain_max_runtime")
    labs_idx = st.session_state.get("labs_index_runtime")
    bmi = st.session_state.get("bmi_runtime")
    bmi_cat = st.session_state.get("bmi_cat_runtime")
    bmi_pen = st.session_state.get("bmi_penalty_runtime")

    hidx, ridx, reinjury = health_index(cond_score, sym_idx, bio_score, p_index, plyo_sc, mc_final, labs_idx, bmi_pen)

    st.markdown("### Índices finais")
    cols = st.columns(6)
    cols[0].metric("Health", f"{hidx:.0f}" if hidx is not None else "—")
    cols[1].metric("Risco", f"{ridx:.0f}" if ridx is not None else "—")
    cols[2].metric("Recidiva", f"{reinjury:.0f}" if reinjury is not None else "—")
    cols[3].metric("IMC", f"{bmi:.1f}" if bmi is not None else "—")
    cols[4].metric("IMC categoria", bmi_cat)
    cols[5].metric("Labs Index", f"{labs_idx:.0f}" if labs_idx is not None else "—")

    st.divider()
    st.markdown("### Comparação com avaliação anterior (se houver)")
    if prev_assessment:
        prev = prev_assessment["data"]

        def g(d, path, default=None):
            cur = d
            for p in path:
                if isinstance(cur, dict) and p in cur:
                    cur = cur[p]
                else:
                    return default
            return cur

        comp = pd.DataFrame([
            ["Health", g(prev, ["indices","health_index"]), hidx],
            ["Risco", g(prev, ["indices","risk_index"]), ridx],
            ["Recidiva", g(prev, ["indices","reinjury_risk"]), reinjury],
            ["Cond", g(prev, ["cardio","cond_score"]), cond_score],
            ["VO2", g(prev, ["cardio","vo2"]), vo2],
            ["Simetria", g(prev, ["perimetry","sym_index"]), sym_idx],
            ["Pliometria", g(prev, ["plyo","plyo_score"]), plyo_sc],
            ["Biomec", g(prev, ["biomech","score"]), bio_score],
            ["Dor", g(prev, ["pain","index"]), p_index],
            ["Motor", g(prev, ["motor_control","final_score"]), mc_final],
            ["Labs", g(prev, ["labs","labs_index"]), labs_idx],
            ["IMC", g(prev, ["anthro","bmi"]), bmi],
        ], columns=["Métrica", "Anterior", "Atual"])
        st.dataframe(comp, use_container_width=True)
    else:
        st.info("Sem avaliação anterior ainda.")

    st.divider()
    st.markdown("### Gráficos (histórico)")
    if assessments:
        rows = []
        for a in reversed(assessments):
            d = a["data"]
            dt = a["eval_date"]

            def g2(path, default=None):
                cur = d
                for p in path:
                    if isinstance(cur, dict) and p in cur:
                        cur = cur[p]
                    else:
                        return default
                return cur

            rows.append({
                "data": pd.to_datetime(dt),
                "Health": g2(["indices","health_index"]),
                "Risco": g2(["indices","risk_index"]),
                "Recidiva": g2(["indices","reinjury_risk"]),
                "Cond": g2(["cardio","cond_score"]),
                "Simetria": g2(["perimetry","sym_index"]),
                "Pliometria": g2(["plyo","plyo_score"]),
                "Biomec": g2(["biomech","score"]),
                "Dor": g2(["pain","index"]),
                "Motor": g2(["motor_control","final_score"]),
                "Labs": g2(["labs","labs_index"]),
                "IMC": g2(["anthro","bmi"]),
            })

        df = pd.DataFrame(rows).sort_values("data").set_index("data")
        st.line_chart(df[["Health","Risco","Recidiva"]])
        st.line_chart(df[["Cond","Simetria","Pliometria","Biomec","Dor","Motor","Labs"]])
    else:
        st.info("Sem histórico ainda.")

    st.divider()
    st.markdown("### Salvar avaliação")
    eval_date = st.date_input("Data da avaliação", value=date.today(), key="eval_date")
    eval_time = st.time_input("Horário", value=datetime.now().time(), key="eval_time")
    notes = st.text_area("Observações gerais (opcional)", height=80, key="notes")

    if st.button("✅ SALVAR", type="primary"):
        eval_dt = datetime.combine(eval_date, eval_time).isoformat()

        data = {
            "meta": {"created_at": datetime.now().isoformat(), "notes": notes or None},
            "perimetry": {"sym_index": sym_idx},
            "cardio": {"cond_score": cond_score, "vo2": vo2, "vo2_score": vo2_score},
            "plyo": {"plyo_score": plyo_sc},
            "biomech": {"score": bio_score},
            "posture": {"index": posture_index, "flags": posture_flags},
            "motor_control": {"final_score": mc_final},
            "pain": {"avg": avg_pain, "max": max_pain, "index": p_index},
            "anthro": {"bmi": bmi, "bmi_category": bmi_cat, "bmi_penalty": bmi_pen},
            "labs": {
                "labs_index": labs_idx,
                "alerts": st.session_state.get("labs_flags_runtime", []),
                "table": st.session_state.get("labs_table_runtime", [])
            },
            "indices": {"health_index": hidx, "risk_index": ridx, "reinjury_risk": reinjury}
        }

        db_insert_assessment(patient_id, eval_dt, data)
        st.success("Avaliação salva! Atualizando…")
        st.rerun()
