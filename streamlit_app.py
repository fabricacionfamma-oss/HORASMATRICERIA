import streamlit as st
import pandas as pd
import re
from datetime import datetime, timedelta
import tempfile
import os
from collections import defaultdict
from fpdf import FPDF

# ==========================================
# 1. CONFIGURACIÓN Y ESTILOS
# ==========================================
st.set_page_config(page_title="Reporte Matricería", layout="centered", page_icon="📅")

st.markdown("""
<style>
    .header-style { font-size: 26px; font-weight: bold; margin-bottom: 5px; color: #1F2937; text-align: center; }
</style>
""", unsafe_allow_html=True)

st.markdown('<div class="header-style">📅 Reporte Gerencial de Matricería</div>', unsafe_allow_html=True)
st.write("<p style='text-align: center;'>Cálculo de horas de matricería.</p>", unsafe_allow_html=True)
st.divider()

# ==========================================
# 2. ENLACES Y CONSTANTES
# ==========================================
SHEETS_CONFIG = [
    # ASISTENCIA
    {"url": "https://docs.google.com/spreadsheets/d/1sccnOPuosjMSepp0FZoEGteYArIIhB2fGH7TeSRW_7E/export?format=csv&gid=1128388185", "skiprows": 2, "tipo": "asistencia", "empresa": "FUMISCOR"}, 
    {"url": "https://docs.google.com/spreadsheets/d/1UNSCxrTy9TUdggNt0ta0TcsEvT3idaRGWcXE_t8J40I/export?format=csv&gid=979884533", "skiprows": 0, "tipo": "asistencia", "empresa": "FAMMA"}, 
    # CORRECTIVOS
    {"url": "https://docs.google.com/spreadsheets/d/1bL_tnlSXGO_t9tKnhIHT5pZ3DAxivbiq2tFETVxBaVI/export?format=csv&gid=1507213893", "skiprows": 2, "tipo": "correctivo", "empresa": "FUMISCOR"}, 
    {"url": "https://docs.google.com/spreadsheets/d/1A-0mngZdgvZGbqzWjA_awhrwfvca0K4aGqp5NBAoFAY/export?format=csv&gid=238711679", "skiprows": 0, "tipo": "correctivo", "empresa": "FAMMA"}, 
    # PREVENTIVOS
    {"url": "https://docs.google.com/spreadsheets/d/1VqsPNhAlT1kPCltbMWsbkZNFBKdwZRFM5RAmnRV0v3c/export?format=csv&gid=1603203990", "skiprows": 2, "tipo": "preventivo", "empresa": "FUMISCOR"}, 
    {"url": "https://docs.google.com/spreadsheets/d/1MptnOuRfyOAr1EgzNJVygTtNziOSdzXJn-PZDX0pNzc/export?format=csv&gid=324842888", "skiprows": 0, "tipo": "preventivo", "empresa": "FAMMA"} 
]

# Columnas exactas del formulario
VALID_PIEZA_COLS = [
    'PIEZAS RENAULT', 'PIEZAS FAURECIA', 'PIEZAS FIAT', 'PIEZAS DENSO', 
    'PIEZAS PEUGEOT', 'PIEZA FIAT', 'PIEZA NISSAN', 'PIEZA RENAULT', 'NUMERO DE PIEZA'
]

# Filtro Extremo Anti-Basura para evitar que las horas se dividan erróneamente
INVALID_PIECES = [
    'NAN', 'NONE', '-', '', 'NO APLICA', 'NOAPLICA', 'N/A', 'NA', 'OK', 'NOK', 'NO', 
    'SI', 'SÍ', 'PENDIENTE', 'NO LLEVA', 'NO TIENE', 'NINGUNO', 'NINGUNA', 
    '0', 'X', '.', ',', 'NO APLICABLE', 'VACIO', 'S/D'
]

def clean_text_standard(text):
    if pd.isna(text): return ""
    text = str(text).upper().strip()
    return re.sub(r'\s+', ' ', text)

def clean_matricero(name):
    name = clean_text_standard(name)
    match = re.match(r'^(\d+)\s*[-_]?\s*(.*)', name)
    if match: return f"{match.group(1)} - {match.group(2).strip()}"
    return name

def get_col_idx(cols, candidates):
    """Busca el índice de una columna priorizando el nombre exacto."""
    for cand in candidates:
        for i, c in enumerate(cols):
            if c.strip() == cand: return i
    for cand in candidates:
        for i, c in enumerate(cols):
            if cand in c: return i
    return None

# ==========================================
# 3. MOTOR DE EXTRACCIÓN 
# ==========================================
@st.cache_data(ttl=300)
def load_data():
    cal_data, mant_data, act_data = [], [], []
    
    for config in SHEETS_CONFIG:
        try:
            df = pd.read_csv(config["url"], skiprows=config["skiprows"])
            
            df.columns = df.columns.astype(str).str.upper().str.strip().str.replace(r'\s+', ' ', regex=True)
            cols = pd.Series(df.columns)
            for dup in cols[cols.duplicated()].unique():
                cols[cols[cols == dup].index.values.tolist()] = [f"{dup}.{i}" if i != 0 else dup for i in range(sum(cols == dup))]
            df.columns = cols
            df_cols = df.columns.tolist()

            idx_fecha = get_col_idx(df_cols, ['FECHA'])
            idx_mat = get_col_idx(df_cols, ['MATRICERO'])
            
            if idx_fecha is None or idx_mat is None: 
                continue

            for _, row in df.iterrows():
                fecha = str(row.iloc[idx_fecha]).strip()
                mat_raw = str(row.iloc[idx_mat]).strip()
                
                if fecha in ['NAN', 'NONE', ''] or mat_raw in ['NAN', 'NONE', '']: 
                    continue
                
                mat = clean_matricero(mat_raw)

                # PREVENTIVO / CORRECTIVO
                if config['tipo'] in ['preventivo', 'correctivo']:
                    idx_hs = next((i for i, c in enumerate(df_cols) if ('HS REALIZADAS' in c or 'HORAS REALIZADAS' in c) and 'TAREA' not in c), None)
                    horas = 0.0
                    if idx_hs is not None and pd.notna(row.iloc[idx_hs]):
                        raw_hs = str(row.iloc[idx_hs]).lower().replace(',', '.')
                        raw_hs = re.sub(r'[^\d.]', '', raw_hs) 
                        try:
                            if raw_hs:
                                val = float(raw_hs)
                                if val > 0: horas = val
                        except: pass
                    
                    if horas <= 0: continue

                    estado = 'NO'
                    c_terms_idx = [i for i, c in enumerate(df_cols) if 'TERMINADO' in c or 'TERMINO' in c]
                    for i_term in reversed(c_terms_idx):
                        if pd.notna(row.iloc[i_term]):
                            val_t = str(row.iloc[i_term]).upper().strip()
                            if 'SI' in val_t or 'SÍ' in val_t: 
                                estado = 'SI'
                                break
                            elif 'NO' in val_t:
                                estado = 'NO'
                                break

                    piezas_found = []
                    for i, col_name in enumerate(df_cols):
                        base_col = col_name.split('.')[0].strip()
                        if base_col in VALID_PIEZA_COLS:
                            val_pieza = clean_text_standard(row.iloc[i])
                            if val_pieza and val_pieza not in INVALID_PIECES:
                                op_val = '-'
                                for j in range(i+1, min(i+4, len(df_cols))):
                                    if 'OPERACION' in df_cols[j] or 'OPERACIÓN' in df_cols[j]:
                                        o_v = clean_text_standard(row.iloc[j])
                                        if o_v not in ['NAN', 'NONE', '']: op_val = o_v
                                        break
                                
                                piezas_found.append({'matriz': val_pieza, 'op': op_val})

                    if piezas_found:
                        hs_per_piece = horas / len(piezas_found)
                        for p in piezas_found:
                            mant_data.append({
                                'FECHA': fecha, 'MATRICERO': mat, 'MATRIZ': p['matriz'], 
                                'OPERACION': p['op'], 'TIPO': config['tipo'].upper(),
                                'HORAS': hs_per_piece, 'TERMINADO': estado, 'EMPRESA': config['empresa']
                            })
                        cal_data.append({'FECHA': fecha, 'MATRICERO': mat, 'TOTAL_HORAS': horas, 'EMPRESA': config['empresa']})

                # ASISTENCIA
                elif config['tipo'] == 'asistencia':
                    horas_asist_totales = 0.0
                    for i in range(1, 5):
                        idx_tarea = next((idx for idx, c in enumerate(df_cols) if (f'{i} - TAREA' in c or f'TAREA {i}' in c) and 'HS' not in c and 'OBS' not in c and 'DESEA' not in c), None)
                        idx_hs_tarea = next((idx for idx, c in enumerate(df_cols) if f'TAREA {i}' in c and ('HS' in c or 'HORAS' in c)), None)

                        if idx_tarea is not None and idx_hs_tarea is not None:
                            t_val = clean_text_standard(row.iloc[idx_tarea])
                            
                            if t_val and t_val not in ['NAN', 'NONE', '-']:
                                raw_hs = str(row.iloc[idx_hs_tarea]).lower().replace(',', '.')
                                raw_hs = re.sub(r'[^\d.]', '', raw_hs)
                                try:
                                    if raw_hs:
                                        h_val = float(raw_hs)
                                        if h_val > 0:
                                            act_data.append({'FECHA': fecha, 'MATRICERO': mat, 'TAREA': t_val, 'HORAS': h_val, 'EMPRESA': config['empresa']})
                                            horas_asist_totales += h_val
                                except: pass

                    if horas_asist_totales > 0:
                        cal_data.append({'FECHA': fecha, 'MATRICERO': mat, 'TOTAL_HORAS': horas_asist_totales, 'EMPRESA': config['empresa']})

        except Exception as e:
            print(f"Error procesando {config['url']}: {e}")
            pass
            
    # ==========================
    # AGRUPACIÓN DE DATOS
    # ==========================
    df_calendario = pd.DataFrame(cal_data)
    if not df_calendario.empty:
        df_calendario['FECHA'] = pd.to_datetime(df_calendario['FECHA'], errors='coerce', dayfirst=True)
        df_calendario = df_calendario.dropna(subset=['FECHA'])
        df_calendario = df_calendario.groupby(['FECHA', 'MATRICERO', 'EMPRESA'], as_index=False)['TOTAL_HORAS'].sum()

    df_mantenimiento = pd.DataFrame(mant_data)
    if not df_mantenimiento.empty:
        df_mantenimiento['FECHA'] = pd.to_datetime(df_mantenimiento['FECHA'], errors='coerce', dayfirst=True)
        df_mantenimiento = df_mantenimiento.dropna(subset=['FECHA'])

    df_actividades = pd.DataFrame(act_data)
    if not df_actividades.empty:
        df_actividades['FECHA'] = pd.to_datetime(df_actividades['FECHA'], errors='coerce', dayfirst=True)
        df_actividades = df_actividades.dropna(subset=['FECHA'])

    return df_calendario, df_mantenimiento, df_actividades

df_raw, df_mant_raw, df_act_raw = load_data()

# ==========================================
# 4. INTERFAZ Y FILTROS DE FECHA
# ==========================================
col1, col2 = st.columns(2)
today = datetime.now()
inicio_mes = today.replace(day=1)

with col1:
    start_date = st.date_input("📅 Fecha de Inicio", inicio_mes)
with col2:
    end_date = st.date_input("📅 Fecha de Fin", today)

st.caption("💡 *Se recomienda que la fecha de inicio sea un día Lunes para una mejor visualización de las semanas en el PDF.*")

if start_date > end_date:
    st.error("La fecha de inicio no puede ser mayor a la fecha de fin.")
    st.stop()

# ==========================================
# 5. CLASE PDF (FPDF) Y LÓGICA DE DIBUJO
# ==========================================
class PDF(FPDF):
    def __init__(self, start_date, end_date, empresa=None):
        super().__init__(orientation='L', unit='mm', format='A4')
        self.rango = f"{start_date.strftime('%d/%m/%Y')} al {end_date.strftime('%d/%m/%Y')}"
        self.empresa = empresa
        self.set_auto_page_break(auto=True, margin=15)
        
    def header(self):
        self.set_font("Arial", 'B', 16)
        self.set_text_color(31, 41, 55)
        title = "Reporte Gerencial - Area de Matriceria"
        if self.empresa:
            title += f" ({self.empresa})"
            
        self.cell(0, 8, title, border=0, ln=True, align='C')
        self.set_font("Arial", 'I', 10)
        self.set_text_color(100, 100, 100)
        self.cell(0, 6, f"Periodo seleccionado: {self.rango}", border=0, ln=True, align='C')
        self.ln(3)

    def footer(self):
        self.set_y(-15)
        self.set_font("Arial", "I", 8)
        self.set_text_color(128, 128, 128)
        self.cell(0, 10, f"Pagina {self.page_no()}", 0, 0, "C")

def clean_text(text):
    return str(text).encode('latin-1', 'replace').decode('latin-1')

def build_pdf(df_datos_orig, df_mant_orig, df_act_orig, s_date, e_date, empresa=None):
    if empresa:
        df_datos = df_datos_orig[df_datos_orig['EMPRESA'] == empresa].copy() if not df_datos_orig.empty else df_datos_orig
        df_mant = df_mant_orig[df_mant_orig['EMPRESA'] == empresa].copy() if not df_mant_orig.empty else df_mant_orig
        df_act = df_act_orig[df_act_orig['EMPRESA'] == empresa].copy() if not df_act_orig.empty else df_act_orig
    else:
        df_datos, df_mant, df_act = df_datos_orig.copy(), df_mant_orig.copy(), df_act_orig.copy()

    pdf = PDF(s_date, e_date, empresa)
    meses_es = ["", "ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO", "JULIO", "AGOSTO", "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE"]
    dias_espanol = ["LUNES", "MARTES", "MIÉRCOLES", "JUEVES", "VIERNES", "SÁBADO", "DOMINGO"]
    
    # -------------------------------------------------------------
    # CÁLCULO ESTRICTO DE FECHAS SELECCIONADAS
    # -------------------------------------------------------------
    delta = e_date - s_date
    all_dates = [s_date + timedelta(days=i) for i in range(delta.days + 1)]
    
    months_dict = defaultdict(list)
    for d in all_dates: months_dict[(d.year, d.month)].append(d)

    if not df_datos.empty:
        mask_period = (df_datos['FECHA'].dt.date >= s_date) & (df_datos['FECHA'].dt.date <= e_date)
        df_period = df_datos.loc[mask_period]
        all_matriceros = sorted(df_period['MATRICERO'].unique()) if not df_period.empty else []
    else:
        all_matriceros = []

    if not all_matriceros:
        pdf.add_page()
        pdf.set_font("Arial", '', 12)
        pdf.cell(0, 10, "No hay horas cargadas para el rango y empresa seleccionados.", ln=True, align='C')
        return pdf.output(dest='S').encode('latin-1')

    # =========================================================
    # HOJA 1: RESUMEN GENERAL DEL INTERVALO DE TIEMPO
    # =========================================================
    pdf.add_page()
    pdf.set_font("Arial", 'B', 14)
    pdf.set_text_color(31, 73, 125)
    pdf.cell(0, 8, f"RESUMEN GENERAL DE ASISTENCIA: {s_date.strftime('%d/%m/%Y')} al {e_date.strftime('%d/%m/%Y')}", ln=True, align='L')
    pdf.ln(2)

    working_days = sum(1 for d in all_dates if d.weekday() < 5)
    estimated_hs = working_days * 8
    
    pdf.set_font("Arial", 'I', 8)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 5, f"Calculo exacto al intervalo indicado: Se detectaron {working_days} dias habiles x 8 hs = {estimated_hs} hs estimadas por persona.", ln=True, align='L')
    pdf.ln(2)

    pdf.set_font("Arial", 'B', 9)
    pdf.set_fill_color(0, 0, 0)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(196, 6, "TABLA GENERAL DE HORAS POR MATRICERO", border=1, ln=True, align='C', fill=True)

    pdf.set_fill_color(31, 73, 125)
    pdf.cell(70, 6, "MATRICERO", border=1, align='C', fill=True)
    pdf.cell(40, 6, "ESTIMADO DE HS", border=1, align='C', fill=True)
    pdf.cell(40, 6, "HS CARGADAS", border=1, align='C', fill=True)
    pdf.set_fill_color(192, 0, 0)
    pdf.cell(46, 6, "FALTANTE / DIFERENCIA", border=1, align='C', ln=True, fill=True)

    total_estimado = 0
    total_cargadas = 0
    total_diferencia = 0

    pdf.set_font("Arial", 'B', 9)
    for mat in all_matriceros:
        df_mat = df_period[df_period['MATRICERO'] == mat]
        reported = df_mat['TOTAL_HORAS'].sum()
        diff = reported - estimated_hs

        total_estimado += estimated_hs
        total_cargadas += reported
        total_diferencia += diff

        pdf.set_fill_color(240, 240, 240)
        pdf.set_text_color(0, 0, 0)
        pdf.cell(70, 6, clean_text(mat[:35]), border=1, fill=True)
        
        pdf.set_fill_color(255, 255, 255)
        pdf.cell(40, 6, str(estimated_hs), border=1, align='C', fill=True)
        
        t_rep = str(int(reported)) if reported == int(reported) else f"{reported:.1f}"
        pdf.cell(40, 6, t_rep, border=1, align='C', fill=True)

        if diff < 0: pdf.set_text_color(192, 0, 0) 
        elif diff > 0: pdf.set_text_color(0, 128, 0)
        else: pdf.set_text_color(0, 0, 0)
        
        sign = "+" if diff > 0 else ""
        t_diff = f"{sign}{int(diff)}" if diff == int(diff) else f"{sign}{diff:.1f}"
        pdf.cell(46, 6, t_diff, border=1, align='C', ln=True, fill=True)

    # TOTAL GENERAL
    pdf.set_font("Arial", 'B', 9)
    pdf.set_fill_color(220, 220, 220)
    pdf.set_text_color(0, 0, 0)
    pdf.cell(70, 7, "TOTAL GENERAL", border=1, align='R', fill=True)
    pdf.cell(40, 7, str(int(total_estimado)), border=1, align='C', fill=True)
    t_rep_tot = str(int(total_cargadas)) if total_cargadas == int(total_cargadas) else f"{total_cargadas:.1f}"
    pdf.cell(40, 7, t_rep_tot, border=1, align='C', fill=True)

    if total_diferencia < 0: pdf.set_text_color(192, 0, 0) 
    elif total_diferencia > 0: pdf.set_text_color(0, 128, 0)
    else: pdf.set_text_color(0, 0, 0)
    
    sign_tot = "+" if total_diferencia > 0 else ""
    t_diff_tot = f"{sign_tot}{int(total_diferencia)}" if total_diferencia == int(total_diferencia) else f"{sign_tot}{total_diferencia:.1f}"
    pdf.cell(46, 7, t_diff_tot, border=1, align='C', ln=True, fill=True)

    # =========================================================
    # CALENDARIOS SEMANALES (VISUALES POR MES)
    # =========================================================
    for (year, month), dates_in_month in months_dict.items():
        pdf.add_page()
        pdf.set_font("Arial", 'B', 14)
        pdf.set_text_color(31, 73, 125)
        pdf.cell(0, 8, f"CALENDARIO SEMANAL: {meses_es[month]} {year}", ln=True, align='L')
        pdf.ln(2)

        weeks_dict = {}
        for d in dates_in_month:
            w = d.isocalendar()[1]
            if w not in weeks_dict:
                monday = d - timedelta(days=d.weekday())
                weeks_dict[w] = [monday + timedelta(days=i) for i in range(7)]

        w_mat, w_day = 65, 28 
        total_w = w_mat + (7 * w_day)
        req_h = 16 + (len(all_matriceros) * 8) + 5

        for week_num, full_week in weeks_dict.items():
            if pdf.get_y() + req_h > 185: 
                pdf.add_page()
                pdf.set_font("Arial", 'B', 12)
                pdf.set_text_color(31, 73, 125)
                pdf.cell(0, 8, f"CALENDARIO: {meses_es[month]} {year} (Cont.)", ln=True, align='L')
                pdf.ln(2)

            pdf.set_font("Arial", 'B', 9)
            pdf.set_fill_color(0, 0, 0)
            pdf.set_text_color(255, 255, 255)
            pdf.cell(total_w, 6, f"SEMANA {week_num}", border=1, ln=True, align='C', fill=True)

            pdf.set_fill_color(31, 73, 125)
            x_s = pdf.get_x()
            pdf.cell(w_mat, 10, "MATRICERO", border=1, align='C', fill=True)
            x_d = pdf.get_x()
            
            for d in full_week: pdf.cell(w_day, 5, clean_text(dias_espanol[d.weekday()]), border='LTR', align='C', fill=True)
            pdf.ln()
            pdf.set_x(x_d) 
            for d in full_week: pdf.cell(w_day, 5, d.strftime('%d/%m/%Y'), border='LBR', align='C', fill=True)
            pdf.ln()

            pdf.set_font("Arial", 'B', 9)
            for mat in all_matriceros:
                pdf.set_fill_color(240, 240, 240)
                pdf.set_text_color(0, 0, 0)
                pdf.cell(w_mat, 8, clean_text(mat[:32]), border=1, fill=True)
                
                df_mat = df_period[df_period['MATRICERO'] == mat]
                for d in full_week:
                    val = df_mat[df_mat['FECHA'].dt.date == d]['TOTAL_HORAS'].sum()
                    if val == 0:
                        pdf.set_fill_color(127, 127, 127) 
                        pdf.set_text_color(255, 255, 255)
                    elif val == 8:
                        pdf.set_fill_color(198, 239, 206) 
                        pdf.set_text_color(0, 97, 0)
                    elif val > 8:
                        pdf.set_fill_color(255, 199, 206) 
                        pdf.set_text_color(156, 0, 6)
                    else:
                        pdf.set_fill_color(255, 235, 156) 
                        pdf.set_text_color(156, 101, 0)

                    t_val = str(int(val)) if val == int(val) else f"{val:.1f}"
                    pdf.cell(w_day, 8, t_val, border=1, align='C', fill=True)
                pdf.ln()
            pdf.ln(5)

    # =========================================================
    # HOJA 2: MANTENIMIENTO PREVENTIVO Y CORRECTIVO
    # =========================================================
    pdf.add_page()
    pdf.set_font("Arial", 'B', 14)
    pdf.set_text_color(31, 73, 125)
    pdf.cell(0, 8, "ANEXO 1: ESTADO DE MATRICES (MANTENIMIENTO)", ln=True, align='L')
    pdf.set_font("Arial", 'I', 9)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 5, "Muestra horas invertidas y estado final.", ln=True)
    pdf.ln(3)

    def draw_mant_table(df_sub, title, force_new_page=False):
        if force_new_page:
            pdf.add_page() # <-- FUERZA UN SALTO DE PÁGINA CUANDO SE REQUIERE
        
        pdf.set_font("Arial", 'B', 12)
        pdf.set_text_color(31, 73, 125)
        pdf.cell(0, 8, f"MANTENIMIENTO {title}", ln=True, align='L')
        
        if df_sub.empty:
            pdf.set_font("Arial", '', 10)
            pdf.set_text_color(0, 0, 0)
            pdf.cell(0, 7, f"No se registraron mantenimientos {title.lower()}s en este periodo.", ln=True)
            pdf.ln(5)
            return

        pdf.set_font("Arial", 'B', 9)
        pdf.set_fill_color(0, 0, 0)
        pdf.set_text_color(255, 255, 255)
        
        pdf.cell(115, 7, "MATRIZ / PIEZA", border=1, fill=True)
        pdf.cell(40, 7, "OPERACIÓN", border=1, align='C', fill=True)
        pdf.cell(30, 7, "HS INSUMIDAS", border=1, align='C', fill=True)
        pdf.cell(40, 7, "ESTADO AL CIERRE", border=1, align='C', ln=True, fill=True)

        pdf.set_font("Arial", '', 9)
        total_hs = 0

        for _, row in df_sub.iterrows():
            matriz = str(row['MATRIZ'])
            operacion = str(row['OPERACION'])
            estado = str(row['ULTIMO_ESTADO']).upper()
            total_hs += row['HS_ACUMULADAS']
            
            pdf.set_fill_color(255, 255, 255)
            pdf.set_text_color(0, 0, 0)
            pdf.cell(115, 7, clean_text(matriz[:60]), border=1)
            pdf.cell(40, 7, clean_text(operacion[:22]), border=1, align='C')
            
            hs_txt = str(int(row['HS_ACUMULADAS'])) if row['HS_ACUMULADAS'] == int(row['HS_ACUMULADAS']) else f"{row['HS_ACUMULADAS']:.1f}"
            pdf.cell(30, 7, hs_txt, border=1, align='C')
            
            if "SI" in estado or "SÍ" in estado:
                pdf.set_text_color(0, 128, 0)
                estado_print = "TERMINADO"
            else:
                pdf.set_text_color(192, 0, 0)
                estado_print = "PENDIENTE"
            
            pdf.cell(40, 7, clean_text(estado_print), border=1, align='C', ln=True)

        # FILA TOTALES
        pdf.set_font("Arial", 'B', 9)
        pdf.set_fill_color(220, 220, 220)
        pdf.set_text_color(0, 0, 0)
        pdf.cell(155, 7, f"TOTAL HORAS {title}", border=1, align='R', fill=True)
        
        t_hs_txt = str(int(total_hs)) if total_hs == int(total_hs) else f"{total_hs:.1f}"
        pdf.cell(30, 7, t_hs_txt, border=1, align='C', fill=True)
        pdf.cell(40, 7, "", border=1, align='C', ln=True, fill=True)
        pdf.ln(5)

    if not df_mant.empty:
        mask_m = (df_mant['FECHA'].dt.date >= s_date) & (df_mant['FECHA'].dt.date <= e_date)
        df_m_period = df_mant.loc[mask_m].copy()
        
        if not df_m_period.empty:
            df_m_period = df_m_period.sort_values('FECHA')
            
            df_m_period['MATRIZ'] = df_m_period['MATRIZ'].astype(str).str.upper().str.strip()
            df_m_period['OPERACION'] = df_m_period['OPERACION'].astype(str).str.upper().str.strip()
            
            resumen_mant = df_m_period.groupby(['MATRIZ', 'OPERACION', 'TIPO']).agg(
                HS_ACUMULADAS=('HORAS', 'sum'),
                ULTIMO_ESTADO=('TERMINADO', 'last')
            ).reset_index()

            df_prev = resumen_mant[resumen_mant['TIPO'] == 'PREVENTIVO'].sort_values('HS_ACUMULADAS', ascending=False)
            df_corr = resumen_mant[resumen_mant['TIPO'] == 'CORRECTIVO'].sort_values('HS_ACUMULADAS', ascending=False)

            # Preventivo usa la página actual del Anexo 1
            draw_mant_table(df_prev, "PREVENTIVO", force_new_page=False)
            # Correctivo obliga una nueva página
            draw_mant_table(df_corr, "CORRECTIVO", force_new_page=True)
        else:
            pdf.set_font("Arial", '', 10)
            pdf.set_text_color(0, 0, 0)
            pdf.cell(0, 7, "No se registraron mantenimientos en este periodo.", ln=True)
    else:
        pdf.set_font("Arial", '', 10)
        pdf.set_text_color(0, 0, 0)
        pdf.cell(0, 7, "No hubo mantenimiento en este periodo.", ln=True)

    # =========================================================
    # PARTE 3: ASISTENCIA 
    # =========================================================
    pdf.add_page() # <-- SALTO DE PÁGINA PARA LA TABLA DE ASISTENCIA
    pdf.set_font("Arial", 'B', 14)
    pdf.set_text_color(31, 73, 125)
    pdf.cell(0, 8, "ANEXO 2: ACTIVIDADES DE ASISTENCIA", ln=True, align='L')
    pdf.set_font("Arial", 'I', 9)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 5, "Resumen de horas insumidas por tarea general.", ln=True)
    pdf.ln(3)

    if not df_act.empty:
        mask_a = (df_act['FECHA'].dt.date >= s_date) & (df_act['FECHA'].dt.date <= e_date)
        df_a_period = df_act.loc[mask_a].copy()
        
        if not df_a_period.empty:
            df_a_period['TAREA'] = df_a_period['TAREA'].astype(str).str.upper().str.strip()
            resumen_act = df_a_period.groupby('TAREA')['HORAS'].sum().reset_index().sort_values('HORAS', ascending=False)
            
            pdf.set_font("Arial", 'B', 9)
            pdf.set_fill_color(31, 73, 125)
            pdf.set_text_color(255, 255, 255)
            pdf.cell(165, 7, "ACTIVIDAD / TAREA", border=1, fill=True)
            pdf.cell(30, 7, "HS TOTALES", border=1, align='C', ln=True, fill=True)

            pdf.set_font("Arial", '', 9)
            pdf.set_text_color(0, 0, 0)
            total_hs_act = 0

            for _, row in resumen_act.iterrows():
                total_hs_act += row['HORAS']
                pdf.cell(165, 7, clean_text(str(row['TAREA'])[:85]), border=1)
                hs_txt = str(int(row['HORAS'])) if row['HORAS'] == int(row['HORAS']) else f"{row['HORAS']:.1f}"
                pdf.cell(30, 7, hs_txt, border=1, align='C', ln=True)

            # FILA TOTALES
            pdf.set_font("Arial", 'B', 9)
            pdf.set_fill_color(220, 220, 220)
            pdf.cell(165, 7, "TOTAL HORAS ASISTENCIA", border=1, align='R', fill=True)
            
            t_hs_act_txt = str(int(total_hs_act)) if total_hs_act == int(total_hs_act) else f"{total_hs_act:.1f}"
            pdf.cell(30, 7, t_hs_act_txt, border=1, align='C', ln=True, fill=True)

        else:
            pdf.set_font("Arial", '', 10)
            pdf.set_text_color(0, 0, 0)
            pdf.cell(0, 7, "No se registraron tareas de asistencia en este periodo.", ln=True)
    else:
        pdf.set_font("Arial", '', 10)
        pdf.set_text_color(0, 0, 0)
        pdf.cell(0, 7, "No se registraron tareas de asistencia en la base de datos.", ln=True)

    temp_pdf = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    pdf.output(temp_pdf.name)
    with open(temp_pdf.name, "rb") as f:
        pdf_bytes = f.read()
    os.remove(temp_pdf.name)
    return pdf_bytes

# ==========================================
# 6. BOTONES DE DESCARGA (FILTROS DE EMPRESA)
# ==========================================
st.write("---")
st.markdown("<h4 style='text-align: center;'>Generar Reportes en PDF</h4>", unsafe_allow_html=True)
st.write("") 

col_btn1, col_btn2, col_btn3 = st.columns(3)

with col_btn1:
    if st.button("🖨️ Procesar Completo", type="primary", use_container_width=True):
        with st.spinner("Generando reporte unificado..."):
            try:
                pdf_data = build_pdf(df_raw, df_mant_raw, df_act_raw, start_date, end_date, empresa=None)
                st.success("¡Reporte Completo listo!")
                st.download_button(
                    label="📥 Descargar Completo", 
                    data=pdf_data, 
                    file_name=f"Reporte_Matriceria_Completo_{start_date.strftime('%d%m%Y')}.pdf", 
                    mime="application/pdf", 
                    use_container_width=True
                )
            except Exception as e:
                st.error(f"Error generando PDF: {e}")

with col_btn2:
    if st.button("🏭 Solo Fumiscor", type="secondary", use_container_width=True):
        with st.spinner("Generando reporte Fumiscor..."):
            try:
                pdf_data = build_pdf(df_raw, df_mant_raw, df_act_raw, start_date, end_date, empresa="FUMISCOR")
                st.success("¡Reporte Fumiscor listo!")
                st.download_button(
                    label="📥 Descargar Fumiscor", 
                    data=pdf_data, 
                    file_name=f"Reporte_Matriceria_Fumiscor_{start_date.strftime('%d%m%Y')}.pdf", 
                    mime="application/pdf", 
                    use_container_width=True
                )
            except Exception as e:
                st.error(f"Error generando PDF: {e}")

with col_btn3:
    if st.button("⚙️ Solo Famma", type="secondary", use_container_width=True):
        with st.spinner("Generando reporte Famma..."):
            try:
                pdf_data = build_pdf(df_raw, df_mant_raw, df_act_raw, start_date, end_date, empresa="FAMMA")
                st.success("¡Reporte Famma listo!")
                st.download_button(
                    label="📥 Descargar Famma", 
                    data=pdf_data, 
                    file_name=f"Reporte_Matriceria_Famma_{start_date.strftime('%d%m%Y')}.pdf", 
                    mime="application/pdf", 
                    use_container_width=True
                )
            except Exception as e:
                st.error(f"Error generando PDF: {e}")
