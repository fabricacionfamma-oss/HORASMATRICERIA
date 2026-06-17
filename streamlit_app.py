import streamlit as st
import pandas as pd
import re
from datetime import datetime, timedelta
import tempfile
import os
import calendar
import plotly.express as px
import plotly.graph_objects as go
from collections import defaultdict
from fpdf import FPDF

# ==========================================
# 1. CONFIGURACIÓN Y ESTILOS
# ==========================================
st.set_page_config(page_title="Reporte Matricería", layout="centered", page_icon="📅")

st.markdown("""
<style>
    .header-style { font-size: 26px; font-weight: bold; margin-bottom: 5px; color: #1F2937; text-align: center; }
    .section-box { padding: 20px; border-radius: 10px; border: 1px solid #e5e7eb; margin-bottom: 25px; background-color: #f9fafb; }
</style>
""", unsafe_allow_html=True)

st.markdown('<div class="header-style">📅 Reporte Gerencial de Matricería</div>', unsafe_allow_html=True)
st.write("<p style='text-align: center;'>Cálculo de horas de matricería y resumen ejecutivo.</p>", unsafe_allow_html=True)
st.divider()

# ==========================================
# 2. ENLACES Y CONSTANTES
# ==========================================
SHEETS_CONFIG = [
    {"url": "https://docs.google.com/spreadsheets/d/1sccnOPuosjMSepp0FZoEGteYArIIhB2fGH7TeSRW_7E/export?format=csv&gid=1128388185", "skiprows": 2, "tipo": "asistencia", "empresa": "FUMISCOR"}, 
    {"url": "https://docs.google.com/spreadsheets/d/1UNSCxrTy9TUdggNt0ta0TcsEvT3idaRGWcXE_t8J40I/export?format=csv&gid=979884533", "skiprows": 0, "tipo": "asistencia", "empresa": "FAMMA"}, 
    {"url": "https://docs.google.com/spreadsheets/d/1bL_tnlSXGO_t9tKnhIHT5pZ3DAxivbiq2tFETVxBaVI/export?format=csv&gid=1507213893", "skiprows": 2, "tipo": "correctivo", "empresa": "FUMISCOR"}, 
    {"url": "https://docs.google.com/spreadsheets/d/1A-0mngZdgvZGbqzWjA_awhrwfvca0K4aGqp5NBAoFAY/export?format=csv&gid=238711679", "skiprows": 0, "tipo": "correctivo", "empresa": "FAMMA"}, 
    {"url": "https://docs.google.com/spreadsheets/d/1VqsPNhAlT1kPCltbMWsbkZNFBKdwZRFM5RAmnRV0v3c/export?format=csv&gid=1603203990", "skiprows": 2, "tipo": "preventivo", "empresa": "FUMISCOR"}, 
    {"url": "https://docs.google.com/spreadsheets/d/1MptnOuRfyOAr1EgzNJVygTtNziOSdzXJn-PZDX0pNzc/export?format=csv&gid=324842888", "skiprows": 0, "tipo": "preventivo", "empresa": "FAMMA"} 
]

VALID_PIEZA_COLS = [
    'PIEZAS RENAULT', 'PIEZAS FAURECIA', 'PIEZAS FIAT', 'PIEZAS DENSO', 
    'PIEZAS PEUGEOT', 'PIEZA FIAT', 'PIEZA NISSAN', 'PIEZA RENAULT', 'NUMERO DE PIEZA'
]

INVALID_PIECES = [
    'NAN', 'NONE', '-', '', 'NO APLICA', 'NOAPLICA', 'N/A', 'NA', 'OK', 'NOK', 'NO', 
    'SI', 'SÍ', 'PENDIENTE', 'NO LLEVA', 'NO TIENE', 'NINGUNO', 'NINGUNA', 
    '0', 'X', '.', ',', 'NO APLICABLE', 'VACIO', 'S/D'
]

meses_lista = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]

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
    for cand in candidates:
        for i, c in enumerate(cols):
            if c.strip() == cand: return i
    for cand in candidates:
        for i, c in enumerate(cols):
            if cand in c: return i
    return None

def parse_hours(raw_hs):
    if pd.isna(raw_hs): return 0.0
    s = str(raw_hs).lower().strip()
    if not s or s in ['nan', 'none']: return 0.0
    
    if ':' in s:
        try:
            parts = s.split(':')
            h = float(re.sub(r'[^\d.]', '', parts[0])) if re.sub(r'[^\d.]', '', parts[0]) else 0.0
            m = float(re.sub(r'[^\d.]', '', parts[1])) if len(parts) > 1 and re.sub(r'[^\d.]', '', parts[1]) else 0.0
            return h + (m / 60.0)
        except:
            return 0.0
            
    s = s.replace(',', '.')
    s = re.sub(r'[^\d.]', '', s)
    try:
        if s:
            if s.count('.') > 1:
                s = s.replace('.', '', s.count('.') - 1)
            val = float(s)
            if val >= 100: 
                val = val / 100
            return val
    except:
        pass
    return 0.0

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
            
            if idx_fecha is None or idx_mat is None: continue

            for _, row in df.iterrows():
                fecha = str(row.iloc[idx_fecha]).strip()
                mat_raw = str(row.iloc[idx_mat]).strip()
                
                if fecha in ['NAN', 'NONE', ''] or mat_raw in ['NAN', 'NONE', '']: continue
                mat = clean_matricero(mat_raw)

                if config['tipo'] in ['preventivo', 'correctivo']:
                    idx_hs = next((i for i, c in enumerate(df_cols) if ('HS REALIZADAS' in c or 'HORAS REALIZADAS' in c) and 'TAREA' not in c), None)
                    horas = parse_hours(row.iloc[idx_hs]) if idx_hs is not None else 0.0
                    
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

                elif config['tipo'] == 'asistencia':
                    horas_asist_totales = 0.0
                    for i in range(1, 5):
                        idx_tarea = next((idx for idx, c in enumerate(df_cols) if (f'{i} - TAREA' in c or f'TAREA {i}' in c) and 'HS' not in c and 'OBS' not in c and 'DESEA' not in c), None)
                        idx_hs_tarea = next((idx for idx, c in enumerate(df_cols) if f'TAREA {i}' in c and ('HS' in c or 'HORAS' in c)), None)

                        if idx_tarea is not None and idx_hs_tarea is not None:
                            t_val = clean_text_standard(row.iloc[idx_tarea])
                            if t_val and t_val not in ['NAN', 'NONE', '-']:
                                h_val = parse_hours(row.iloc[idx_hs_tarea])
                                if h_val > 0:
                                    act_data.append({'FECHA': fecha, 'MATRICERO': mat, 'TAREA': t_val, 'HORAS': h_val, 'EMPRESA': config['empresa']})
                                    horas_asist_totales += h_val

                    if horas_asist_totales > 0:
                        cal_data.append({'FECHA': fecha, 'MATRICERO': mat, 'TOTAL_HORAS': horas_asist_totales, 'EMPRESA': config['empresa']})
        except Exception as e:
            pass
            
    df_calendario = pd.DataFrame(cal_data)
    if not df_calendario.empty:
        df_calendario['FECHA'] = pd.to_datetime(df_calendario['FECHA'], errors='coerce', dayfirst=True)
        # Limpieza profunda de los nombres
        df_calendario['MATRICERO'] = df_calendario['MATRICERO'].astype(str).str.strip()
        df_calendario = df_calendario.dropna(subset=['FECHA'])
        df_calendario = df_calendario.groupby(['FECHA', 'MATRICERO', 'EMPRESA'], as_index=False)['TOTAL_HORAS'].sum()

    df_mantenimiento = pd.DataFrame(mant_data)
    if not df_mantenimiento.empty:
        df_mantenimiento['FECHA'] = pd.to_datetime(df_mantenimiento['FECHA'], errors='coerce', dayfirst=True)
        df_mantenimiento['MATRICERO'] = df_mantenimiento['MATRICERO'].astype(str).str.strip()
        df_mantenimiento = df_mantenimiento.dropna(subset=['FECHA'])

    df_actividades = pd.DataFrame(act_data)
    if not df_actividades.empty:
        df_actividades['FECHA'] = pd.to_datetime(df_actividades['FECHA'], errors='coerce', dayfirst=True)
        df_actividades['MATRICERO'] = df_actividades['MATRICERO'].astype(str).str.strip()
        df_actividades = df_actividades.dropna(subset=['FECHA'])

    return df_calendario, df_mantenimiento, df_actividades

with st.spinner("Conectando y descargando bases de datos..."):
    df_raw, df_mant_raw, df_act_raw = load_data()


# ==========================================
# 4. CLASE PDF (FPDF) COMÚN Y FUNCIONES
# ==========================================
class PDF(FPDF):
    def __init__(self, start_date, end_date, empresa=None, title_override=None):
        super().__init__(orientation='L', unit='mm', format='A4')
        if start_date == end_date:
            self.rango = f"{start_date.strftime('%d/%m/%Y')}"
        else:
            self.rango = f"{start_date.strftime('%d/%m/%Y')} al {end_date.strftime('%d/%m/%Y')}"
        
        self.empresa = empresa
        self.title_override = title_override
        self.set_auto_page_break(auto=True, margin=15)
        
    def header(self):
        self.set_font("Arial", 'B', 16)
        self.set_text_color(31, 41, 55)
        title = self.title_override if self.title_override else "Reporte Gerencial - Area de Matriceria"
        if self.empresa:
            title += f" ({self.empresa})"
            
        self.cell(0, 8, title, border=0, ln=True, align='C')
        self.set_font("Arial", 'I', 10)
        self.set_text_color(100, 100, 100)
        self.cell(0, 6, f"Periodo: {self.rango}", border=0, ln=True, align='C')
        self.ln(3)

    def footer(self):
        self.set_y(-15)
        self.set_font("Arial", "I", 8)
        self.set_text_color(128, 128, 128)
        self.cell(0, 10, f"Pagina {self.page_no()}", 0, 0, "C")

def clean_text(text):
    return str(text).encode('latin-1', 'replace').decode('latin-1')


# ==========================================
# 5. GENERADORES DE PDF
# ==========================================

# --- DASHBOARD EJECUTIVO (MENSUAL) ---
def draw_dashboard_table(pdf, x_start, y_start, title, df_data, col1_name, col2_name, total_hs):
    pdf.set_xy(x_start, y_start)
    pdf.set_font("Arial", 'B', 8)
    pdf.set_fill_color(31, 73, 125)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(90, 6, title, border=1, align='C', fill=True)
    
    pdf.set_xy(x_start, y_start + 6)
    pdf.set_fill_color(220, 220, 220)
    pdf.set_text_color(0, 0, 0)
    pdf.cell(60, 5, col1_name, border=1, fill=True)
    pdf.cell(15, 5, col2_name, border=1, align='C', fill=True)
    pdf.cell(15, 5, "%", border=1, align='C', fill=True)
    
    y = y_start + 11
    pdf.set_font("Arial", '', 7)
    
    if df_data.empty:
        pdf.set_xy(x_start, y)
        pdf.cell(90, 5, "Sin registros en el periodo", border=1, align='C')
        return

    for _, row in df_data.iterrows():
        pdf.set_xy(x_start, y)
        val_name = clean_text(str(row.iloc[0])[:35])
        val_hs = row.iloc[1]
        pct = (val_hs / total_hs * 100) if total_hs > 0 else 0
        
        pdf.cell(60, 5, val_name, border=1)
        pdf.cell(15, 5, f"{val_hs:.1f}", border=1, align='C')
        pdf.cell(15, 5, f"{pct:.1f}%", border=1, align='C')
        y += 5

def build_pdf_dashboard(df_mant_orig, df_act_orig, s_date, e_date, mes_nombre, empresa=None):
    if empresa:
        df_mant = df_mant_orig[df_mant_orig['EMPRESA'] == empresa].copy() if not df_mant_orig.empty else pd.DataFrame()
        df_act = df_act_orig[df_act_orig['EMPRESA'] == empresa].copy() if not df_act_orig.empty else pd.DataFrame()
    else:
        df_mant, df_act = df_mant_orig.copy(), df_act_orig.copy()

    df_mant_anual = df_mant[df_mant['FECHA'].dt.year == s_date.year] if not df_mant.empty else pd.DataFrame()
    df_act_anual = df_act[df_act['FECHA'].dt.year == s_date.year] if not df_act_anual.empty else pd.DataFrame()

    df_mant_mes = df_mant_anual[(df_mant_anual['FECHA'].dt.date >= s_date) & (df_mant_anual['FECHA'].dt.date <= e_date)] if not df_mant_anual.empty else pd.DataFrame()
    df_act_mes = df_act_anual[(df_act_anual['FECHA'].dt.date >= s_date) & (df_act_anual['FECHA'].dt.date <= e_date)] if not df_act_anual.empty else pd.DataFrame()

    pdf = PDF(s_date, e_date, empresa, title_override=f"RESUMEN EJECUTIVO - {mes_nombre.upper()} {s_date.year}")
    pdf.add_page()
    
    # 1. Calcular Totales (Del Mes)
    hs_prev = df_mant_mes[df_mant_mes['TIPO'] == 'PREVENTIVO']['HORAS'].sum() if not df_mant_mes.empty else 0
    hs_corr = df_mant_mes[df_mant_mes['TIPO'] == 'CORRECTIVO']['HORAS'].sum() if not df_mant_mes.empty else 0
    hs_asis = df_act_mes['HORAS'].sum() if not df_act_mes.empty else 0
    hs_total = hs_prev + hs_corr + hs_asis

    # 2. Dibujar Tabla Centralizada de Métricas (Solo 4 columnas)
    y_metrics = 25
    widths = [50, 50, 50, 50]
    x_start = (297 - sum(widths)) / 2 

    pdf.set_xy(x_start, y_metrics)
    pdf.set_font("Arial", 'B', 9)
    pdf.set_fill_color(245, 245, 245) 
    pdf.set_text_color(0, 0, 0)
    
    pdf.cell(widths[0], 5, "HS DE MANTENIMIENTO", border='LTR', align='C', fill=True)
    pdf.cell(widths[1], 5, "HS DE MANTENIMIENTO", border='LTR', align='C', fill=True)
    pdf.cell(widths[2], 10, "HS DE ASISTENCIA", border=1, align='C', fill=True)
    pdf.cell(widths[3], 10, "TOTAL DE HS", border=1, align='C', fill=True)

    pdf.set_xy(x_start, y_metrics + 5)
    pdf.cell(widths[0], 5, "PREVENTIVO", border='LBR', align='C', fill=True)
    pdf.cell(widths[1], 5, "CORRECTIVO", border='LBR', align='C', fill=True)

    pdf.set_xy(x_start, y_metrics + 10)
    pdf.set_font("Arial", 'B', 14)
    vals = [
        f"{hs_prev:.0f}" if hs_prev.is_integer() else f"{hs_prev:.1f}",
        f"{hs_corr:.0f}" if hs_corr.is_integer() else f"{hs_corr:.1f}",
        f"{hs_asis:.0f}" if hs_asis.is_integer() else f"{hs_asis:.1f}",
        f"{hs_total:.0f}" if hs_total.is_integer() else f"{hs_total:.1f}"
    ]
    for w, v in zip(widths, vals):
        pdf.cell(w, 8, v, border='LTR', align='C')

    pdf.set_xy(x_start, y_metrics + 18)
    pdf.set_font("Arial", 'B', 11)
    pcts = [
        f"{(hs_prev/hs_total*100):.0f}%" if hs_total > 0 else "0%",
        f"{(hs_corr/hs_total*100):.0f}%" if hs_total > 0 else "0%",
        f"{(hs_asis/hs_total*100):.0f}%" if hs_total > 0 else "0%",
        "100%" if hs_total > 0 else "0%"
    ]
    colors = [(44, 160, 44), (214, 39, 40), (31, 119, 180), (0, 0, 0)]
    
    for w, p, c in zip(widths, pcts, colors):
        pdf.set_text_color(*c)
        pdf.cell(w, 6, p, border='LBR', align='C')
        
    pdf.set_text_color(0, 0, 0)
    y_charts = y_metrics + 28

    # 3. Dibujar Gráficos
    df_trend = pd.DataFrame()
    if not df_mant_anual.empty or not df_act_anual.empty:
        parts = []
        if not df_mant_anual.empty: parts.append(df_mant_anual[['FECHA', 'TIPO', 'HORAS']])
        if not df_act_anual.empty: parts.append(df_act_anual[['FECHA', 'HORAS']].assign(TIPO='ASISTENCIA'))
        df_trend = pd.concat(parts)
    
    if not df_trend.empty:
        meses_full = {1:'ENERO', 2:'FEBRERO', 3:'MARZO', 4:'ABRIL', 5:'MAYO', 6:'JUNIO', 7:'JULIO', 8:'AGOSTO', 9:'SEPTIEMBRE', 10:'OCTUBRE', 11:'NOVIEMBRE', 12:'DICIEMBRE'}
        all_months_df = pd.DataFrame([{'MES_NUM': k, 'MES': v, 'TIPO': t, 'HORAS': 0.0} 
                                      for k, v in meses_full.items() 
                                      for t in ['PREVENTIVO', 'CORRECTIVO', 'ASISTENCIA']])
                                      
        df_trend['MES_NUM'] = df_trend['FECHA'].dt.month
        df_trend['MES'] = df_trend['MES_NUM'].map(meses_full)
        trend_grp = df_trend.groupby(['MES_NUM', 'MES', 'TIPO'])['HORAS'].sum().reset_index()
        trend_grp = pd.concat([all_months_df, trend_grp]).groupby(['MES_NUM', 'MES', 'TIPO'])['HORAS'].sum().reset_index()
        
        trend_grp['LABEL'] = trend_grp['HORAS'].apply(lambda x: (f"{x:.0f}" if x.is_integer() else f"{x:.1f}") if x > 0 else "")

        fig_trend = px.bar(trend_grp, x='MES', y='HORAS', color='TIPO', barmode='group', text='LABEL',
                           color_discrete_map={'PREVENTIVO':'#2ca02c', 'CORRECTIVO':'#d62728', 'ASISTENCIA':'#1f77b4'})
        
        fig_trend.update_traces(
            textposition='outside', 
            textfont_size=8, 
            textangle=-90, 
            cliponaxis=False
        )
        fig_trend.update_xaxes(categoryorder='array', categoryarray=list(meses_full.values()), title="")
        fig_trend.update_yaxes(title="HS DE MATRICERIA")
        fig_trend.update_layout(
            title=f"Evolución Mensual ({s_date.year})", 
            margin=dict(t=30, b=40, l=10, r=10), 
            height=300, width=800, 
            legend=dict(
                orientation="h", 
                yanchor="top", 
                y=-0.1, 
                xanchor="center", 
                x=0.5,
                title="" 
            )
        )
    else:
        fig_trend = go.Figure()
        fig_trend.update_layout(title=f"Sin datos para la Evolución Anual {s_date.year}", height=300, width=800)

    fig_pie = go.Figure(data=[go.Pie(labels=['PREVENTIVO', 'CORRECTIVO', 'ASISTENCIA'], 
                                     values=[hs_prev, hs_corr, hs_asis], 
                                     marker_colors=['#2ca02c', '#d62728', '#1f77b4'], hole=0.4)])
    fig_pie.update_layout(
        title=f"Distribución ({mes_nombre.title()})", 
        margin=dict(t=30, b=40, l=10, r=10), 
        height=300, width=350,
        legend=dict(orientation="h", yanchor="top", y=-0.1, xanchor="center", x=0.5)
    )
    
    with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp_trend, \
         tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp_pie:
        fig_trend.write_image(tmp_trend.name, engine="kaleido")
        fig_pie.write_image(tmp_pie.name, engine="kaleido")
        
        pdf.image(tmp_trend.name, x=5, y=y_charts, w=190)
        pdf.image(tmp_pie.name, x=195, y=y_charts, w=95)
        
        os.remove(tmp_trend.name)
        os.remove(tmp_pie.name)

    # 4. Tablas Top 20 (Hoja 2)
    pdf.add_page()
    pdf.set_font("Arial", 'B', 14)
    pdf.set_text_color(31, 73, 125)
    pdf.cell(0, 10, f"DETALLE DE PRINCIPALES CONSUMOS DE HORAS (TOP 20) - {mes_nombre.upper()}", ln=True, align='C')
    pdf.ln(2)

    top_p, top_c, top_a = pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    if not df_mant_mes.empty:
        df_p = df_mant_mes[df_mant_mes['TIPO'] == 'PREVENTIVO']
        if not df_p.empty:
            df_p = df_p.copy()
            df_p['MAQUINA'] = df_p['MATRIZ'] + " OP" + df_p['OPERACION'].astype(str)
            top_p = df_p.groupby('MAQUINA')['HORAS'].sum().reset_index().sort_values('HORAS', ascending=False).head(20)

        df_c = df_mant_mes[df_mant_mes['TIPO'] == 'CORRECTIVO']
        if not df_c.empty:
            df_c = df_c.copy()
            df_c['MAQUINA'] = df_c['MATRIZ'] + " OP" + df_c['OPERACION'].astype(str)
            top_c = df_c.groupby('MAQUINA')['HORAS'].sum().reset_index().sort_values('HORAS', ascending=False).head(20)

    if not df_act_mes.empty:
        top_a = df_act_mes.groupby('MATRICERO')['HORAS'].sum().reset_index().sort_values('HORAS', ascending=False).head(20)

    y_tables = pdf.get_y()
    draw_dashboard_table(pdf, 10, y_tables, "TOP 20 MATRICES - PREVENTIVO", top_p, "MAQUINA", "HS", hs_prev)
    draw_dashboard_table(pdf, 105, y_tables, "TOP 20 MATRICES - CORRECTIVO", top_c, "MAQUINA", "HS", hs_corr)
    draw_dashboard_table(pdf, 200, y_tables, "HS ASISTENCIA POR MATRICERO", top_a, "MATRICERO", "HS", hs_asis)

    # 5. Hoja 3 - Asistencia por Tarea/Actividad
    pdf.add_page()
    pdf.set_font("Arial", 'B', 14)
    pdf.set_text_color(31, 73, 125)
    pdf.cell(0, 10, f"DETALLE DE ASISTENCIA POR ACTIVIDAD - {mes_nombre.upper()}", ln=True, align='C')
    pdf.ln(5)

    if not df_act_mes.empty:
        top_act = df_act_mes.groupby('TAREA')['HORAS'].sum().reset_index().sort_values('HORAS', ascending=False)
        x_start_act = (297 - 240) / 2
        
        pdf.set_font("Arial", 'B', 10)
        pdf.set_fill_color(31, 73, 125)
        pdf.set_text_color(255, 255, 255)
        
        pdf.set_x(x_start_act)
        pdf.cell(180, 8, "ACTIVIDAD / TAREA", border=1, fill=True)
        pdf.cell(30, 8, "HS TOTALES", border=1, align='C', fill=True)
        pdf.cell(30, 8, "%", border=1, align='C', ln=True, fill=True)

        pdf.set_font("Arial", '', 9)
        pdf.set_text_color(0, 0, 0)

        for _, row in top_act.iterrows():
            pdf.set_x(x_start_act)
            val_name = clean_text(str(row['TAREA'])[:95])
            val_hs = row['HORAS']
            pct = (val_hs / hs_asis * 100) if hs_asis > 0 else 0
            
            pdf.cell(180, 7, val_name, border=1)
            pdf.cell(30, 7, f"{val_hs:.1f}", border=1, align='C')
            pdf.cell(30, 7, f"{pct:.1f}%", border=1, align='C', ln=True)

        pdf.set_font("Arial", 'B', 10)
        pdf.set_fill_color(220, 220, 220)
        pdf.set_x(x_start_act)
        pdf.cell(180, 8, "TOTAL HORAS ASISTENCIA", border=1, align='R', fill=True)
        pdf.cell(30, 8, f"{hs_asis:.1f}", border=1, align='C', fill=True)
        pdf.cell(30, 8, "100.0%", border=1, align='C', ln=True, fill=True)
    else:
        pdf.set_font("Arial", '', 11)
        pdf.set_text_color(0, 0, 0)
        pdf.cell(0, 10, "Sin registros de asistencia en el periodo", ln=True, align='C')

    temp_pdf = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    pdf.output(temp_pdf.name)
    with open(temp_pdf.name, "rb") as f:
        pdf_bytes = f.read()
    os.remove(temp_pdf.name)
    return pdf_bytes

# --- REPORTE DETALLADO (CALENDARIO) ---
def build_pdf_detailed(df_datos_orig, df_mant_orig, df_act_orig, s_date, e_date, empresa=None, dias_habiles_custom=None):
    s_ts = pd.to_datetime(s_date)
    e_ts = pd.to_datetime(e_date)
    
    if empresa:
        df_datos = df_datos_orig[df_datos_orig['EMPRESA'] == empresa].copy() if not df_datos_orig.empty else df_datos_orig
        df_mant = df_mant_orig[df_mant_orig['EMPRESA'] == empresa].copy() if not df_mant_orig.empty else df_mant_orig
        df_act = df_act_orig[df_act_orig['EMPRESA'] == empresa].copy() if not df_act_orig.empty else df_act_orig
    else:
        df_datos, df_mant, df_act = df_datos_orig.copy(), df_mant_orig.copy(), df_act_orig.copy()

    pdf = PDF(s_date, e_date, empresa, title_override="Reporte Detallado - Area de Matriceria")
    meses_es = ["", "ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO", "JULIO", "AGOSTO", "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE"]
    dias_espanol = ["LUNES", "MARTES", "MIÉRCOLES", "JUEVES", "VIERNES", "SÁBADO", "DOMINGO"]
    
    delta = e_date - s_date
    all_dates = [s_date + timedelta(days=i) for i in range(delta.days + 1)]
    months_dict = defaultdict(list)
    for d in all_dates: months_dict[(d.year, d.month)].append(d)

    if not df_datos.empty:
        mask_period = (df_datos['FECHA'] >= s_ts) & (df_datos['FECHA'] <= e_ts)
        df_period = df_datos.loc[mask_period]
        all_matriceros = sorted(df_period['MATRICERO'].unique()) if not df_period.empty else []
    else:
        all_matriceros = []

    if not all_matriceros:
        pdf.add_page()
        pdf.set_font("Arial", '', 12)
        pdf.cell(0, 10, "No hay horas cargadas para el rango seleccionado.", ln=True, align='C')
        return pdf.output(dest='S').encode('latin-1')

    pdf.add_page()
    pdf.set_font("Arial", 'B', 14)
    pdf.set_text_color(31, 73, 125)
    pdf.cell(0, 8, f"RESUMEN DE ASISTENCIA: {s_date.strftime('%d/%m/%Y')} al {e_date.strftime('%d/%m/%Y')}", ln=True, align='L')
    pdf.ln(2)

    working_days = dias_habiles_custom if dias_habiles_custom is not None else sum(1 for d in all_dates if d.weekday() < 5)
    estimated_hs = working_days * 8
    
    pdf.set_font("Arial", 'I', 8)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 5, f"Cálculo: Se consideran {working_days} días hábiles (ajuste manual) x 8 hs = {estimated_hs} hs estimadas.", ln=True, align='L')
    pdf.ln(2)

    pdf.set_font("Arial", 'B', 9)
    pdf.set_fill_color(0, 0, 0)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(196, 6, "TABLA GENERAL DE HORAS", border=1, ln=True, align='C', fill=True)

    pdf.set_fill_color(31, 73, 125)
    pdf.cell(70, 6, "MATRICERO", border=1, align='C', fill=True)
    pdf.cell(40, 6, "ESTIMADO DE HS", border=1, align='C', fill=True)
    pdf.cell(40, 6, "HS CARGADAS", border=1, align='C', fill=True)
    pdf.set_fill_color(192, 0, 0)
    pdf.cell(46, 6, "FALTANTE / DIFERENCIA", border=1, align='C', ln=True, fill=True)

    total_estimado = total_cargadas = total_diferencia = 0
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

    for (year, month), dates_in_month in months_dict.items():
        pdf.add_page()
        pdf.set_font("Arial", 'B', 14)
        pdf.set_text_color(31, 73, 125)
        pdf.cell(0, 8, f"CALENDARIO: {meses_es[month]} {year}", ln=True, align='L')
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
                
                # Optimización para el calendario general
                hs_dict = df_period[df_period['MATRICERO'] == mat].groupby(df_period['FECHA'].dt.date)['TOTAL_HORAS'].sum().to_dict()
                for d in full_week:
                    val = hs_dict.get(d, 0.0)
                    if val == 0:
                        pdf.set_fill_color(127, 127, 127); pdf.set_text_color(255, 255, 255)
                    elif val == 8:
                        pdf.set_fill_color(198, 239, 206); pdf.set_text_color(0, 97, 0)
                    elif val > 8:
                        pdf.set_fill_color(255, 199, 206); pdf.set_text_color(156, 0, 6)
                    else:
                        pdf.set_fill_color(255, 235, 156); pdf.set_text_color(156, 101, 0)
                    t_val = str(int(val)) if val == int(val) else f"{val:.1f}"
                    pdf.cell(w_day, 8, t_val, border=1, align='C', fill=True)
                pdf.ln()
            pdf.ln(5)

    def draw_mant_table(df_sub, title, force_new_page=False):
        if force_new_page: pdf.add_page()
        pdf.set_font("Arial", 'B', 12)
        pdf.set_text_color(31, 73, 125)
        pdf.cell(0, 8, f"MANTENIMIENTO {title}", ln=True, align='L')
        
        if df_sub.empty:
            pdf.set_font("Arial", '', 10); pdf.set_text_color(0, 0, 0)
            pdf.cell(0, 7, f"No se registraron mantenimientos {title.lower()}s en este periodo.", ln=True); pdf.ln(5)
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
            total_hs += row['HS_ACUMULADAS']
            estado = str(row['ULTIMO_ESTADO']).upper()
            pdf.set_fill_color(255, 255, 255); pdf.set_text_color(0, 0, 0)
            pdf.cell(115, 7, clean_text(str(row['MATRIZ'])[:60]), border=1)
            pdf.cell(40, 7, clean_text(str(row['OPERACION'])[:22]), border=1, align='C')
            hs_txt = str(int(row['HS_ACUMULADAS'])) if row['HS_ACUMULADAS'] == int(row['HS_ACUMULADAS']) else f"{row['HS_ACUMULADAS']:.1f}"
            pdf.cell(30, 7, hs_txt, border=1, align='C')
            if "SI" in estado or "SÍ" in estado:
                pdf.set_text_color(0, 128, 0); estado_print = "TERMINADO"
            else:
                pdf.set_text_color(192, 0, 0); estado_print = "PENDIENTE"
            pdf.cell(40, 7, clean_text(estado_print), border=1, align='C', ln=True)

        pdf.set_font("Arial", 'B', 9)
        pdf.set_fill_color(220, 220, 220); pdf.set_text_color(0, 0, 0)
        pdf.cell(155, 7, f"TOTAL HORAS {title}", border=1, align='R', fill=True)
        t_hs_txt = str(int(total_hs)) if total_hs == int(total_hs) else f"{total_hs:.1f}"
        pdf.cell(30, 7, t_hs_txt, border=1, align='C', fill=True)
        pdf.cell(40, 7, "", border=1, align='C', ln=True, fill=True)
        pdf.ln(5)

    pdf.add_page()
    pdf.set_font("Arial", 'B', 14)
    pdf.set_text_color(31, 73, 125)
    pdf.cell(0, 8, "ANEXO 1: ESTADO DE MATRICES (MANTENIMIENTO)", ln=True, align='L')
    pdf.ln(3)

    if not df_mant.empty:
        mask_m = (df_mant['FECHA'] >= s_ts) & (df_mant['FECHA'] <= e_ts)
        df_m_period = df_mant.loc[mask_m].copy()
        if not df_m_period.empty:
            df_m_period['MATRIZ'] = df_m_period['MATRIZ'].astype(str).str.upper().str.strip()
            df_m_period['OPERACION'] = df_m_period['OPERACION'].astype(str).str.upper().str.strip()
            resumen_mant = df_m_period.groupby(['MATRIZ', 'OPERACION', 'TIPO']).agg(HS_ACUMULADAS=('HORAS', 'sum'), ULTIMO_ESTADO=('TERMINADO', 'last')).reset_index()

            df_prev = resumen_mant[resumen_mant['TIPO'] == 'PREVENTIVO'].sort_values('HS_ACUMULADAS', ascending=False)
            df_corr = resumen_mant[resumen_mant['TIPO'] == 'CORRECTIVO'].sort_values('HS_ACUMULADAS', ascending=False)

            draw_mant_table(df_prev, "PREVENTIVO", force_new_page=False)
            draw_mant_table(df_corr, "CORRECTIVO", force_new_page=True)
        else:
            pdf.set_font("Arial", '', 10); pdf.set_text_color(0, 0, 0); pdf.cell(0, 7, "No se registraron mantenimientos en este periodo.", ln=True)

    pdf.add_page()
    pdf.set_font("Arial", 'B', 14)
    pdf.set_text_color(31, 73, 125)
    pdf.cell(0, 8, "ANEXO 2: ACTIVIDADES DE ASISTENCIA", ln=True, align='L')
    pdf.ln(3)

    if not df_act.empty:
        mask_a = (df_act['FECHA'] >= s_ts) & (df_act['FECHA'] <= e_ts)
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

            pdf.set_font("Arial", 'B', 9)
            pdf.set_fill_color(220, 220, 220)
            pdf.cell(165, 7, "TOTAL HORAS ASISTENCIA", border=1, align='R', fill=True)
            t_hs_act_txt = str(int(total_hs_act)) if total_hs_act == int(total_hs_act) else f"{total_hs_act:.1f}"
            pdf.cell(30, 7, t_hs_act_txt, border=1, align='C', ln=True, fill=True)
        else:
            pdf.set_font("Arial", '', 10); pdf.set_text_color(0, 0, 0); pdf.cell(0, 7, "No se registraron tareas de asistencia en este periodo.", ln=True)

    temp_pdf = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    pdf.output(temp_pdf.name)
    with open(temp_pdf.name, "rb") as f:
        pdf_bytes = f.read()
    os.remove(temp_pdf.name)
    return pdf_bytes


# --- REPORTE INDIVIDUAL POR MATRICERO ---
def build_pdf_matricero(df_datos_orig, df_mant_orig, df_act_orig, s_date, e_date, matricero, empresa=None):
    # Uso seguro de Fechas en Pandas mediante Timestamp
    s_ts = pd.to_datetime(s_date)
    e_ts = pd.to_datetime(e_date)
    
    # 1. Filtro estricto para Calendario (df_d)
    df_d = pd.DataFrame()
    if not df_datos_orig.empty:
        mask_d = (df_datos_orig['FECHA'] >= s_ts) & (df_datos_orig['FECHA'] <= e_ts) & (df_datos_orig['MATRICERO'] == matricero)
        if empresa: mask_d &= (df_datos_orig['EMPRESA'] == empresa)
        df_d = df_datos_orig.loc[mask_d].copy()

    # 2. Filtro estricto para Mantenimiento (df_m)
    df_m = pd.DataFrame()
    if not df_mant_orig.empty:
        mask_m = (df_mant_orig['FECHA'] >= s_ts) & (df_mant_orig['FECHA'] <= e_ts) & (df_mant_orig['MATRICERO'] == matricero)
        if empresa: mask_m &= (df_mant_orig['EMPRESA'] == empresa)
        df_m = df_mant_orig.loc[mask_m].copy().sort_values('FECHA')

    # 3. Filtro estricto para Asistencia (df_a)
    df_a = pd.DataFrame()
    if not df_act_orig.empty:
        mask_a = (df_act_orig['FECHA'] >= s_ts) & (df_act_orig['FECHA'] <= e_ts) & (df_act_orig['MATRICERO'] == matricero)
        if empresa: mask_a &= (df_act_orig['EMPRESA'] == empresa)
        df_a = df_act_orig.loc[mask_a].copy().sort_values('FECHA')

    pdf = PDF(s_date, e_date, empresa, title_override=f"Reporte Individual - {matricero}")
    pdf.add_page()
    
    # 1. TABLA DE MANTENIMIENTO (PREV/CORR)
    pdf.set_font("Arial", 'B', 12)
    pdf.set_text_color(31, 73, 125)
    pdf.cell(0, 8, "1. ACTIVIDADES DE MANTENIMIENTO (PREVENTIVO Y CORRECTIVO)", ln=True)
    pdf.ln(2)

    if not df_m.empty:
        pdf.set_font("Arial", 'B', 9)
        pdf.set_fill_color(0, 0, 0); pdf.set_text_color(255, 255, 255)
        pdf.cell(25, 7, "FECHA", border=1, align='C', fill=True)
        pdf.cell(25, 7, "TIPO", border=1, align='C', fill=True)
        pdf.cell(145, 7, "MATRIZ / PIEZA - OPERACION", border=1, fill=True)
        pdf.cell(20, 7, "HS", border=1, align='C', fill=True)
        pdf.cell(25, 7, "ESTADO", border=1, align='C', ln=True, fill=True)
        
        pdf.set_font("Arial", '', 8)
        total_hs_m = 0
        for _, row in df_m.iterrows():
            total_hs_m += row['HORAS']
            pdf.set_fill_color(255, 255, 255); pdf.set_text_color(0, 0, 0)
            pdf.cell(25, 6, row['FECHA'].strftime('%d/%m/%Y'), border=1, align='C')
            pdf.cell(25, 6, row['TIPO'], border=1, align='C')
            desc = clean_text(f"{row['MATRIZ']} - OP: {row['OPERACION']}")[:85]
            pdf.cell(145, 6, desc, border=1)
            pdf.cell(20, 6, f"{row['HORAS']:.1f}", border=1, align='C')
            
            estado = str(row['TERMINADO']).upper()
            if "SI" in estado or "SÍ" in estado:
                pdf.set_text_color(0, 128, 0)
            else:
                pdf.set_text_color(192, 0, 0)
            pdf.cell(25, 6, clean_text(estado), border=1, align='C', ln=True)
            
        pdf.set_font("Arial", 'B', 9)
        pdf.set_fill_color(220, 220, 220); pdf.set_text_color(0, 0, 0)
        pdf.cell(195, 7, "TOTAL HORAS MANTENIMIENTO", border=1, align='R', fill=True)
        pdf.cell(45, 7, f"{total_hs_m:.1f}", border=1, align='C', ln=True, fill=True)
    else:
        pdf.set_font("Arial", '', 10); pdf.set_text_color(0, 0, 0)
        pdf.cell(0, 7, "Sin registros de mantenimiento en este periodo.", ln=True)
    
    pdf.ln(5)
    
    # 2. TABLA DE ASISTENCIA
    pdf.set_font("Arial", 'B', 12)
    pdf.set_text_color(31, 73, 125)
    pdf.cell(0, 8, "2. ACTIVIDADES DE ASISTENCIA", ln=True)
    pdf.ln(2)

    if not df_a.empty:
        pdf.set_font("Arial", 'B', 9)
        pdf.set_fill_color(31, 73, 125); pdf.set_text_color(255, 255, 255)
        pdf.cell(25, 7, "FECHA", border=1, align='C', fill=True)
        pdf.cell(195, 7, "TAREA / ACTIVIDAD", border=1, fill=True)
        pdf.cell(20, 7, "HS", border=1, align='C', ln=True, fill=True)
        
        pdf.set_font("Arial", '', 8); pdf.set_text_color(0, 0, 0)
        total_hs_a = 0
        for _, row in df_a.iterrows():
            total_hs_a += row['HORAS']
            pdf.cell(25, 6, row['FECHA'].strftime('%d/%m/%Y'), border=1, align='C')
            pdf.cell(195, 6, clean_text(str(row['TAREA']))[:120], border=1)
            pdf.cell(20, 6, f"{row['HORAS']:.1f}", border=1, align='C', ln=True)
            
        pdf.set_font("Arial", 'B', 9)
        pdf.set_fill_color(220, 220, 220); pdf.set_text_color(0, 0, 0)
        pdf.cell(220, 7, "TOTAL HORAS ASISTENCIA", border=1, align='R', fill=True)
        pdf.cell(20, 7, f"{total_hs_a:.1f}", border=1, align='C', ln=True, fill=True)
    else:
        pdf.set_font("Arial", '', 10); pdf.set_text_color(0, 0, 0)
        pdf.cell(0, 7, "Sin registros de asistencia en este periodo.", ln=True)
        
    # 3. CALENDARIO
    pdf.add_page()
    pdf.set_font("Arial", 'B', 12)
    pdf.set_text_color(31, 73, 125)
    pdf.cell(0, 8, "3. CALENDARIO DE HORAS", ln=True)
    pdf.ln(2)
    
    delta = e_date - s_date
    all_dates = [s_date + timedelta(days=i) for i in range(delta.days + 1)]
    months_dict = defaultdict(list)
    for d in all_dates: months_dict[(d.year, d.month)].append(d)
    meses_es = ["", "ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO", "JULIO", "AGOSTO", "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE"]
    dias_espanol = ["LUNES", "MARTES", "MIÉRCOLES", "JUEVES", "VIERNES", "SÁBADO", "DOMINGO"]
    
    w_day = 30 
    total_w = 7 * w_day
    x_offset = (297 - total_w) / 2
    
    # Optimizador: Diccionario para busqueda ultra rápida de horas
    hs_dict = df_d.groupby(df_d['FECHA'].dt.date)['TOTAL_HORAS'].sum().to_dict() if not df_d.empty else {}
    
    for (year, month), dates_in_month in months_dict.items():
        pdf.set_font("Arial", 'B', 11)
        pdf.set_text_color(0, 0, 0)
        pdf.cell(0, 8, f"MES: {meses_es[month]} {year}", ln=True)
        
        weeks_dict = {}
        for d in dates_in_month:
            w = d.isocalendar()[1]
            if w not in weeks_dict:
                monday = d - timedelta(days=d.weekday())
                weeks_dict[w] = [monday + timedelta(days=i) for i in range(7)]

        for week_num, full_week in weeks_dict.items():
            if pdf.get_y() > 170:
                pdf.add_page()
                
            pdf.set_x(x_offset)
            pdf.set_font("Arial", 'B', 9)
            pdf.set_fill_color(0, 0, 0); pdf.set_text_color(255, 255, 255)
            pdf.cell(total_w, 6, f"SEMANA {week_num}", border=1, ln=True, align='C', fill=True)

            pdf.set_x(x_offset)
            pdf.set_fill_color(31, 73, 125)
            for d in full_week: pdf.cell(w_day, 5, clean_text(dias_espanol[d.weekday()]), border='LTR', align='C', fill=True)
            pdf.ln()
            
            pdf.set_x(x_offset)
            for d in full_week: pdf.cell(w_day, 5, d.strftime('%d/%m/%Y'), border='LBR', align='C', fill=True)
            pdf.ln()

            pdf.set_x(x_offset)
            pdf.set_font("Arial", 'B', 9)
            for d in full_week:
                val = hs_dict.get(d, 0.0) # Búsqueda directa al diccionario
                if val == 0:
                    pdf.set_fill_color(127, 127, 127); pdf.set_text_color(255, 255, 255)
                elif val == 8:
                    pdf.set_fill_color(198, 239, 206); pdf.set_text_color(0, 97, 0)
                elif val > 8:
                    pdf.set_fill_color(255, 199, 206); pdf.set_text_color(156, 0, 6)
                else:
                    pdf.set_fill_color(255, 235, 156); pdf.set_text_color(156, 101, 0)
                t_val = str(int(val)) if val == int(val) else f"{val:.1f}"
                pdf.cell(w_day, 8, t_val, border=1, align='C', fill=True)
            pdf.ln()
            pdf.ln(5)
            
    temp_pdf = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    pdf.output(temp_pdf.name)
    with open(temp_pdf.name, "rb") as f:
        pdf_bytes = f.read()
    os.remove(temp_pdf.name)
    return pdf_bytes


# ==========================================
# 7. INTERFAZ PRINCIPAL: CAJAS DE DESCARGA
# ==========================================

st.write("---")
st.markdown("<h4 style='text-align: center;'>Generar Reportes en PDF</h4>", unsafe_allow_html=True)
st.write("") 

# --- CAJA 1: RESUMEN EJECUTIVO (Solo Mensual) ---
st.markdown('<div class="section-box">', unsafe_allow_html=True)
st.subheader("📊 1. Resumen Ejecutivo (Dashboard Mensual)")
st.write("Genera un PDF con el resumen anual, KPIs y las tablas del Top 20 del mes seleccionado.")

col_m1, col_m2 = st.columns(2)
with col_m1:
    mes_dash = st.selectbox("📅 Seleccione el Mes", meses_lista, index=datetime.now().month - 1, key="mes_dash")
with col_m2:
    anio_dash = st.selectbox("📅 Seleccione el Año", range(2023, 2030), index=datetime.now().year - 2023, key="anio_dash")

mes_num_dash = meses_lista.index(mes_dash) + 1
_, last_day_dash = calendar.monthrange(anio_dash, mes_num_dash)
start_date_dash = datetime(anio_dash, mes_num_dash, 1).date()
end_date_dash = datetime(anio_dash, mes_num_dash, last_day_dash).date()

st.write("")
col_btn1, col_btn2, col_btn3 = st.columns(3)
with col_btn1:
    if st.button("📈 Dashboard Completo", type="primary", use_container_width=True):
        with st.spinner("Generando dashboard..."):
            try:
                pdf_data = build_pdf_dashboard(df_mant_raw, df_act_raw, start_date_dash, end_date_dash, mes_dash, empresa=None)
                st.download_button("📥 Descargar", data=pdf_data, file_name=f"Dashboard_Matriceria_{mes_dash}_{anio_dash}.pdf", mime="application/pdf", use_container_width=True)
            except Exception as e: st.error(f"Error: {e}")

with col_btn2:
    if st.button("📈 Dashboard Fumiscor", type="secondary", use_container_width=True):
        with st.spinner("Generando dashboard..."):
            try:
                pdf_data = build_pdf_dashboard(df_mant_raw, df_act_raw, start_date_dash, end_date_dash, mes_dash, empresa="FUMISCOR")
                st.download_button("📥 Descargar", data=pdf_data, file_name=f"Dashboard_Fumiscor_{mes_dash}_{anio_dash}.pdf", mime="application/pdf", use_container_width=True)
            except Exception as e: st.error(f"Error: {e}")

with col_btn3:
    if st.button("📈 Dashboard Famma", type="secondary", use_container_width=True):
        with st.spinner("Generando dashboard..."):
            try:
                pdf_data = build_pdf_dashboard(df_mant_raw, df_act_raw, start_date_dash, end_date_dash, mes_dash, empresa="FAMMA")
                st.download_button("📥 Descargar", data=pdf_data, file_name=f"Dashboard_Famma_{mes_dash}_{anio_dash}.pdf", mime="application/pdf", use_container_width=True)
            except Exception as e: st.error(f"Error: {e}")
st.markdown('</div>', unsafe_allow_html=True)


# --- CAJA 2: REPORTE DETALLADO (Rango Personalizado) ---
st.markdown('<div class="section-box">', unsafe_allow_html=True)
st.subheader("📅 2. Reporte Detallado (Calendarios y Anexos)")
st.write("Genera el PDF completo con las horas calculadas, calendario de asistencias y anexos para un rango de fechas personalizado.")

col_d_ini, col_d_fin, col_d_hab = st.columns(3)
with col_d_ini:
    start_date_det = st.date_input("📅 Fecha de Inicio", datetime.now().date() - timedelta(days=7), key="start_det")
with col_d_fin:
    end_date_det = st.date_input("📅 Fecha de Fin", datetime.now().date(), key="end_det")
with col_d_hab:
    # Calcula los días hábiles matemáticos para usar de valor sugerido
    dias_defecto = sum(1 for i in range((end_date_det - start_date_det).days + 1) if (start_date_det + timedelta(days=i)).weekday() < 5) if end_date_det >= start_date_det else 0
    dias_habiles_ui = st.number_input("🛠️ Días Hábiles (reales)", min_value=0, value=dias_defecto, step=1, help="Resta los feriados si los hubo")

if start_date_det > end_date_det:
    st.error("La fecha de inicio no puede ser mayor a la fecha de fin.")
else:
    label_file = f"{start_date_det.strftime('%d%m%Y')}_al_{end_date_det.strftime('%d%m%Y')}"
    
    st.write("")
    col_btn4, col_btn5, col_btn6 = st.columns(3)
    with col_btn4:
        if st.button("🖨️ Detallado Completo", type="primary", use_container_width=True):
            with st.spinner("Generando reporte..."):
                try:
                    pdf_data = build_pdf_detailed(df_raw, df_mant_raw, df_act_raw, start_date_det, end_date_det, empresa=None, dias_habiles_custom=dias_habiles_ui)
                    st.download_button("📥 Descargar", data=pdf_data, file_name=f"Reporte_Detallado_{label_file}.pdf", mime="application/pdf", use_container_width=True)
                except Exception as e: st.error(f"Error: {e}")

    with col_btn5:
        if st.button("🖨️ Detallado Fumiscor", type="secondary", use_container_width=True):
            with st.spinner("Generando reporte..."):
                try:
                    pdf_data = build_pdf_detailed(df_raw, df_mant_raw, df_act_raw, start_date_det, end_date_det, empresa="FUMISCOR", dias_habiles_custom=dias_habiles_ui)
                    st.download_button("📥 Descargar", data=pdf_data, file_name=f"Reporte_Detallado_Fumiscor_{label_file}.pdf", mime="application/pdf", use_container_width=True)
                except Exception as e: st.error(f"Error: {e}")

    with col_btn6:
        if st.button("🖨️ Detallado Famma", type="secondary", use_container_width=True):
            with st.spinner("Generando reporte..."):
                try:
                    pdf_data = build_pdf_detailed(df_raw, df_mant_raw, df_act_raw, start_date_det, end_date_det, empresa="FAMMA", dias_habiles_custom=dias_habiles_ui)
                    st.download_button("📥 Descargar", data=pdf_data, file_name=f"Reporte_Detallado_Famma_{label_file}.pdf", mime="application/pdf", use_container_width=True)
                except Exception as e: st.error(f"Error: {e}")
st.markdown('</div>', unsafe_allow_html=True)


# --- CAJA 3: REPORTE INDIVIDUAL POR MATRICERO ---
st.markdown('<div class="section-box">', unsafe_allow_html=True)
st.subheader("👨‍🔧 3. Reporte Individual por Matricero")
st.write("Genera un PDF con las actividades detalladas (Preventivo, Correctivo, Asistencia) y el calendario de horas para un matricero específico.")

# Se genera la lista consolidando y eliminando cualquier rastro de espacios nulos
mats = set()
if not df_raw.empty: mats.update(df_raw['MATRICERO'].dropna().unique())
if not df_mant_raw.empty: mats.update(df_mant_raw['MATRICERO'].dropna().unique())
if not df_act_raw.empty: mats.update(df_act_raw['MATRICERO'].dropna().unique())
lista_matriceros = sorted(list(mats))

col_mat, col_d_ini_mat, col_d_fin_mat = st.columns(3)
with col_mat:
    mat_seleccionado = st.selectbox("👨‍🔧 Seleccione el Matricero", lista_matriceros, key="mat_sel")
with col_d_ini_mat:
    start_date_mat = st.date_input("📅 Fecha de Inicio", datetime.now().date() - timedelta(days=7), key="start_mat")
with col_d_fin_mat:
    end_date_mat = st.date_input("📅 Fecha de Fin", datetime.now().date(), key="end_mat")

if start_date_mat > end_date_mat:
    st.error("La fecha de inicio no puede ser mayor a la fecha de fin.")
elif not lista_matriceros:
    st.warning("No hay datos de matriceros disponibles en este momento.")
else:
    label_file_mat = f"{mat_seleccionado[:10].replace(' ', '_')}_{start_date_mat.strftime('%d%m%Y')}_al_{end_date_mat.strftime('%d%m%Y')}"
    
    st.write("")
    col_btn7, col_btn8, col_btn9 = st.columns(3)
    with col_btn7:
        if st.button("🖨️ Reporte Individual Completo", type="primary", use_container_width=True):
            with st.spinner("Generando reporte individual..."):
                try:
                    pdf_data = build_pdf_matricero(df_raw, df_mant_raw, df_act_raw, start_date_mat, end_date_mat, mat_seleccionado, empresa=None)
                    st.download_button("📥 Descargar", data=pdf_data, file_name=f"Reporte_Individual_{label_file_mat}.pdf", mime="application/pdf", use_container_width=True)
                except Exception as e: st.error(f"Error: {e}")

    with col_btn8:
        if st.button("🖨️ Reporte Fumiscor", type="secondary", use_container_width=True):
            with st.spinner("Generando reporte individual..."):
                try:
                    pdf_data = build_pdf_matricero(df_raw, df_mant_raw, df_act_raw, start_date_mat, end_date_mat, mat_seleccionado, empresa="FUMISCOR")
                    st.download_button("📥 Descargar", data=pdf_data, file_name=f"Reporte_Individual_Fumiscor_{label_file_mat}.pdf", mime="application/pdf", use_container_width=True)
                except Exception as e: st.error(f"Error: {e}")

    with col_btn9:
        if st.button("🖨️ Reporte Famma", type="secondary", use_container_width=True):
            with st.spinner("Generando reporte individual..."):
                try:
                    pdf_data = build_pdf_matricero(df_raw, df_mant_raw, df_act_raw, start_date_mat, end_date_mat, mat_seleccionado, empresa="FAMMA")
                    st.download_button("📥 Descargar", data=pdf_data, file_name=f"Reporte_Individual_Famma_{label_file_mat}.pdf", mime="application/pdf", use_container_width=True)
                except Exception as e: st.error(f"Error: {e}")
st.markdown('</div>', unsafe_allow_html=True)
