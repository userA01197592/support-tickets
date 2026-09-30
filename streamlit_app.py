import datetime
import html
from urllib.parse import urlencode

import altair as alt
import pandas as pd
import streamlit as st
from apify_client import ApifyClient
from streamlit_gsheets import GSheetsConnection

# ===========================================================================
# CONFIGURACIÓN GENERAL Y ESTILO
# ===========================================================================
st.set_page_config(page_title="Vacantes", page_icon="logo.png", layout="wide")
st.logo("logo.png")

AZUL = "#0A4FC2"
TINTA = "#1B2430"
GRIS = "#5A6270"
LINEA = "#E2DCCF"

st.markdown(
    f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Instrument+Serif&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap');
html, body, .stApp, .stMarkdown, button, input, textarea, select {{ font-family: 'IBM Plex Sans', 'Helvetica Neue', sans-serif; }}
.block-container {{ padding-top: 1.2rem; max-width: 1320px; }}
h1, h2, h3 {{ font-family: 'Instrument Serif', Georgia, serif !important; font-weight: 400 !important; letter-spacing: -0.5px; }}
.stButton > button, .stLinkButton > a, .stFormSubmitButton > button {{ border-radius: 8px; min-height: 44px; font-weight: 600; }}
.kicker {{ font-family: 'IBM Plex Mono', monospace; font-size: 12px; letter-spacing: 1.5px; text-transform: uppercase; color: #B4491A; }}
.titulo {{ font-family: 'Instrument Serif', Georgia, serif; font-size: 52px; line-height: 1; letter-spacing: -1px; margin: 6px 0 18px; color: {TINTA}; }}
.marca {{ font-family: 'Instrument Serif', Georgia, serif; font-size: 34px; color: {TINTA}; line-height: 56px; }}
.marca span {{ color: {AZUL}; }}
.badge {{ font-family: 'IBM Plex Mono', monospace; font-size: 13px; color: {GRIS}; text-align: right; padding-top: 16px; }}
.badge b {{ color: {TINTA}; font-weight: 500; background: #fff; border: 1px solid {LINEA}; border-radius: 6px; padding: 5px 9px; }}
.mono {{ font-family: 'IBM Plex Mono', monospace; font-size: 13px; color: {GRIS}; }}
.ini {{ width: 52px; height: 52px; border-radius: 10px; background: {TINTA}; color: #F6F3EC; display: flex; align-items: center; justify-content: center; font-family: 'IBM Plex Mono', monospace; font-weight: 500; }}
.puesto {{ font-size: 18px; font-weight: 600; color: {TINTA}; margin: 0; }}
.empresa {{ font-size: 15px; color: #3A4250; margin: 2px 0 6px; }}
.chip {{ display: inline-block; padding: 3px 8px; border-radius: 999px; background: #E9E4D8; color: #4A5260; font-size: 12px; font-weight: 500; margin-left: 8px; }}
.colhead {{ display: flex; justify-content: space-between; align-items: center; font-weight: 600; font-size: 14px; padding: 10px 12px; background: #EFEBE1; border-radius: 10px; margin-bottom: 8px; }}
.dot {{ display: inline-block; width: 10px; height: 10px; border-radius: 999px; margin-right: 8px; }}
.kcard {{ background: #fff; border: 1px solid {LINEA}; border-radius: 10px; padding: 12px 14px; margin-bottom: 4px; }}
.kcard .t {{ font-size: 15px; font-weight: 600; line-height: 1.3; color: {TINTA}; }}
.kcard .c {{ font-size: 13px; color: #3A4250; margin: 4px 0; }}
.kcard .n {{ font-size: 13px; color: #3A4250; background: #F6F3EC; border-radius: 6px; padding: 6px 8px; margin-top: 6px; }}
.metric-num {{ font-family: 'Instrument Serif', Georgia, serif; font-size: 40px; line-height: 1; text-align: center; }}
.metric-lbl {{ font-size: 13px; color: {GRIS}; text-align: center; }}
</style>
""",
    unsafe_allow_html=True,
)

conn = st.connection("gsheets", type=GSheetsConnection)
esc = html.escape


def iniciales(nombre: str) -> str:
    partes = [p for p in str(nombre).replace(",", " ").split() if p[:1].isalpha()]
    return "".join(p[0] for p in partes[:2]).upper() or "—"


def hace(fecha: str) -> str:
    f = pd.to_datetime(fecha, errors="coerce")
    if pd.isna(f):
        return str(fecha) or "—"
    dias = (pd.Timestamp.now().normalize() - f.tz_localize(None).normalize()).days
    if dias <= 0:
        return "Hoy"
    if dias == 1:
        return "Hace 1 día"
    if dias < 7:
        return f"Hace {dias} días"
    return f"Hace {dias // 7} sem."


# ===========================================================================
# APIFY (LinkedIn)
# ===========================================================================
ACTOR_ID = "curious_coder/linkedin-jobs-scraper"
FECHAS = {"Última semana": "r604800", "Últimas 24 horas": "r86400", "Último mes": "r2592000", "Cualquier fecha": ""}
MODALIDADES = {"Todas": "", "Presencial": "1", "Remoto": "2", "Híbrido": "3"}
MAPA_MODO = {"on-site": "Presencial", "onsite": "Presencial", "remote": "Remoto", "hybrid": "Híbrido"}


def primero(item: dict, *claves):
    for c in claves:
        v = item.get(c)
        if v not in (None, "", []):
            return v
    return ""


@st.cache_data(ttl=300, show_spinner=False)
def credito_apify():
    try:
        lim = ApifyClient(st.secrets["APIFY_TOKEN"]).user("me").limits()
        if not isinstance(lim, dict):
            lim = lim.model_dump(by_alias=True)
        usado = lim["current"]["monthlyUsageUsd"]
        maximo = lim["limits"]["maxMonthlyUsageUsd"]
        return f"${usado:.2f} / ${maximo:.2f}"
    except Exception:
        return None


def buscar_vacantes(puesto, ubicacion, fecha, modo, limite) -> pd.DataFrame:
    params = {"keywords": puesto, "location": ubicacion}
    if FECHAS[fecha]:
        params["f_TPR"] = FECHAS[fecha]
    if MODALIDADES[modo]:
        params["f_WT"] = MODALIDADES[modo]
    url = "https://www.linkedin.com/jobs/search/?" + urlencode(params)

    client = ApifyClient(st.secrets["APIFY_TOKEN"])
    run = client.actor(ACTOR_ID).call(
        run_input={"urls": [url], "limitPerSource": limite, "count": limite}
    )
    if run is None:
        raise RuntimeError("Apify no devolvió resultados.")
    # Compatible con apify-client 1.x (dict) y 2.x (objeto)
    dataset_id = run["defaultDatasetId"] if isinstance(run, dict) else run.default_dataset_id

    filas = []
    for it in client.dataset(dataset_id).iterate_items():
        if not isinstance(it, dict):
            it = dict(it)
        link = primero(it, "link", "jobUrl", "url", "applyUrl")
        modo_raw = str(primero(it, "workplaceType", "workType", "workRemoteAllowed")).lower()
        filas.append({
            "ID": str(primero(it, "id", "jobId") or link),
            "Puesto": primero(it, "title", "jobTitle", "position"),
            "Empresa": primero(it, "companyName", "company"),
            "Ubicación": primero(it, "location", "jobLocation"),
            "Modalidad": MAPA_MODO.get(modo_raw, modo if modo != "Todas" else ""),
            "Nivel": primero(it, "seniorityLevel", "experienceLevel"),
            "Publicada": str(primero(it, "postedAt", "publishedAt", "listedAt", "postedTime"))[:10],
            "Link": link,
            "Descripción": str(primero(it, "descriptionText", "description", "jobDescription"))[:5000],
        })
    return pd.DataFrame(filas).head(limite)


# ===========================================================================
# GOOGLE SHEETS (pestaña "Vacantes")
# ===========================================================================
HOJA = "Vacantes"
COLS = ["ID", "Puesto", "Empresa", "Ubicación", "Modalidad", "Nivel", "Publicada",
        "Link", "Descripción", "Estado", "Notas", "Guardada", "Aplicada"]
ESTADOS = {"Nueva": "#B4491A", "Aplicada": AZUL, "Entrevista": "#2F6B5E",
           "Oferta": "#7A5A12", "Descartada": "#8A8F97"}


def cargar_vacantes() -> pd.DataFrame:
    try:
        df = conn.read(worksheet=HOJA, ttl=0)
    except Exception:
        df = pd.DataFrame(columns=COLS)
        conn.create(worksheet=HOJA, data=df)
    df = df.dropna(how="all")
    for c in COLS:
        if c not in df.columns:
            df[c] = ""
    return df[COLS].fillna("").astype(str)


def guardar_vacantes(df: pd.DataFrame) -> None:
    conn.update(worksheet=HOJA, data=df[COLS])


# ===========================================================================
# ENCABEZADO
# ===========================================================================
if "mensaje" in st.session_state:
    st.toast(st.session_state.pop("mensaje"), icon=":material/check_circle:")

h1, h2, h3 = st.columns([0.6, 6, 3.4], vertical_alignment="center")
h1.image("logo.png", width=56)
h2.markdown('<div class="marca">Vacantes<span>.</span></div>', unsafe_allow_html=True)
credito = credito_apify() if "APIFY_TOKEN" in st.secrets else None
if credito:
    h3.markdown(f'<div class="badge">Crédito Apify este mes &nbsp;<b>{credito}</b></div>', unsafe_allow_html=True)

if "APIFY_TOKEN" not in st.secrets:
    st.error("Falta `APIFY_TOKEN` en los Secrets de la app.")
    st.stop()

guardadas = cargar_vacantes()
tab_buscar, tab_mis, tab_tickets = st.tabs(
    [":material/search: Buscar", ":material/view_kanban: Mis vacantes", ":material/confirmation_number: Tickets"]
)

# ===========================================================================
# PESTAÑA: BUSCAR
# ===========================================================================
with tab_buscar:
    st.markdown('<div class="kicker">LinkedIn · vía Apify</div><div class="titulo">Encuentra tu siguiente puesto</div>',
                unsafe_allow_html=True)

    with st.form("busqueda", border=True):
        c1, c2, c3, c4, c5 = st.columns([2.2, 1.6, 1.2, 1.2, 1], vertical_alignment="bottom")
        puesto = c1.text_input("Puesto o palabras clave", placeholder="supply chain planner")
        ubicacion = c2.text_input("Ubicación", value="Monterrey, N.L.")
        fecha = c3.selectbox("Publicadas en", list(FECHAS))
        modo = c4.selectbox("Modalidad", list(MODALIDADES))
        limite = c5.number_input("Máximo", 10, 100, 25, step=5)
        buscar = st.form_submit_button("Buscar", type="primary", icon=":material/search:")
        st.markdown(f'<span class="mono">Costo estimado: hasta ${limite * 0.002:.2f} USD por búsqueda</span>',
                    unsafe_allow_html=True)

    if buscar:
        if not puesto.strip():
            st.warning("Escribe un puesto o palabra clave.")
        else:
            with st.spinner("Buscando en LinkedIn… (1-2 minutos)"):
                try:
                    st.session_state.resultados = buscar_vacantes(puesto.strip(), ubicacion.strip(), fecha, modo, int(limite))
                    st.session_state.consulta = f"“{puesto.strip()}” en {ubicacion.strip() or 'cualquier lugar'}"
                    for k in [k for k in st.session_state if str(k).startswith("sel_")]:
                        del st.session_state[k]
                    credito_apify.clear()
                except Exception as e:
                    st.error(f"Error al buscar: {e}")

    res = st.session_state.get("resultados")
    if res is not None:
        filtros, lista = st.columns([1.1, 4.5], gap="large")
        with filtros:
            st.markdown("**Mostrar**")
            ocultar = st.checkbox("Ocultar ya guardadas")
            modos_presentes = sorted(m for m in res["Modalidad"].unique() if m)
            filtro_modo = st.radio("Modalidad", ["Todas"] + modos_presentes) if len(modos_presentes) > 1 else "Todas"

        vista = res.copy()
        vista["ya"] = vista["ID"].isin(guardadas["ID"])
        if ocultar:
            vista = vista[~vista["ya"]]
        if filtro_modo != "Todas":
            vista = vista[vista["Modalidad"] == filtro_modo]

        with lista:
            st.markdown(f'**{len(vista)} vacantes** <span style="color:{GRIS}">para {esc(st.session_state.get("consulta", ""))}</span>',
                        unsafe_allow_html=True)
            if vista.empty:
                st.info("No hay vacantes con estos filtros. Prueba con otras palabras o una ubicación más amplia.")
            for _, r in vista.iterrows():
                with st.container(border=True):
                    a, b, c = st.columns([0.6, 6, 2.2], vertical_alignment="center")
                    a.markdown(f'<div class="ini">{esc(iniciales(r["Empresa"]))}</div>', unsafe_allow_html=True)
                    meta = " · ".join(x for x in [r["Ubicación"], r["Modalidad"], r["Nivel"], hace(r["Publicada"])] if x)
                    chip = '<span class="chip">Ya en tu lista</span>' if r["ya"] else ""
                    b.markdown(
                        f'<p class="puesto">{esc(r["Puesto"])}{chip}</p>'
                        f'<p class="empresa">{esc(r["Empresa"])}</p>'
                        f'<span class="mono">{esc(meta)}</span>',
                        unsafe_allow_html=True,
                    )
                    with c:
                        if r["Link"]:
                            st.link_button("Abrir", r["Link"], icon=":material/open_in_new:", use_container_width=True)
                        st.checkbox("Seleccionar", key=f"sel_{r['ID']}", disabled=bool(r["ya"]))

            seleccion = [k[4:] for k, v in st.session_state.items() if str(k).startswith("sel_") and v]
            if seleccion:
                def limpiar():
                    for k in [k for k in st.session_state if str(k).startswith("sel_")]:
                        st.session_state[k] = False

                with st.container(border=True):
                    t, b1, b2 = st.columns([5, 1.3, 2], vertical_alignment="center")
                    t.markdown(f"**{len(seleccion)} seleccionadas** · se guardarán en la pestaña “Vacantes” de tu Google Sheet")
                    b1.button("Limpiar", on_click=limpiar, use_container_width=True)
                    if b2.button("Guardar en Google Sheets", type="primary", icon=":material/bookmark_add:", use_container_width=True):
                        nuevas = res[res["ID"].isin(seleccion) & ~res["ID"].isin(guardadas["ID"])].copy()
                        nuevas["Estado"] = "Nueva"
                        nuevas["Notas"] = ""
                        nuevas["Guardada"] = datetime.date.today().isoformat()
                        nuevas["Aplicada"] = ""
                        guardar_vacantes(pd.concat([nuevas[COLS].astype(str), guardadas], ignore_index=True))
                        for k in [k for k in st.session_state if str(k).startswith("sel_")]:
                            del st.session_state[k]
                        st.session_state.mensaje = f"{len(nuevas)} vacante(s) guardada(s)"
                        st.rerun()


# ===========================================================================
# PESTAÑA: MIS VACANTES (tablero + detalle)
# ===========================================================================
@st.dialog("Detalle de vacante", width="large")
def detalle(vid: str):
    df = cargar_vacantes()
    fila = df[df["ID"] == vid]
    if fila.empty:
        st.warning("No se encontró la vacante.")
        return
    r = fila.iloc[0]
    st.markdown(f'<div class="titulo" style="font-size:38px;margin-bottom:4px">{esc(r["Puesto"])}</div>'
                f'<p class="empresa" style="font-size:17px">{esc(r["Empresa"])}</p>', unsafe_allow_html=True)
    meta = " · ".join(x for x in [r["Ubicación"], r["Modalidad"], r["Nivel"], f'Publicada {hace(r["Publicada"]).lower()}'] if x)
    st.markdown(f'<span class="mono">{esc(meta)}</span>', unsafe_allow_html=True)

    izq, der = st.columns([3, 2], gap="large")
    with izq:
        st.markdown("**Descripción**")
        with st.container(height=380, border=False):
            st.write(r["Descripción"] or "_Sin descripción. Ábrela en LinkedIn para verla completa._")
    with der:
        estado = st.radio("Estado", list(ESTADOS), index=list(ESTADOS).index(r["Estado"]) if r["Estado"] in ESTADOS else 0,
                          horizontal=True)
        notas = st.text_area("Notas", value=r["Notas"], height=140)
        st.markdown(f'<span class="mono">Guardada: {esc(r["Guardada"] or "—")} · Aplicada: {esc(r["Aplicada"] or "—")}</span>',
                    unsafe_allow_html=True)
        if st.button("Guardar cambios", type="primary", use_container_width=True):
            i = fila.index[0]
            df.loc[i, "Estado"] = estado
            df.loc[i, "Notas"] = notas
            if estado == "Aplicada" and not df.loc[i, "Aplicada"]:
                df.loc[i, "Aplicada"] = datetime.date.today().isoformat()
            guardar_vacantes(df)
            st.session_state.mensaje = "Vacante actualizada"
            st.rerun()
        if r["Link"]:
            st.link_button("Ver en LinkedIn", r["Link"], icon=":material/open_in_new:", use_container_width=True)


with tab_mis:
    st.markdown('<div class="kicker">Seguimiento · sincronizado con Google Sheets</div><div class="titulo">Mis vacantes</div>',
                unsafe_allow_html=True)
    if guardadas.empty:
        st.info("Aún no has guardado vacantes. Búscalas en la pestaña **Buscar**.")
    else:
        est = guardadas["Estado"].where(guardadas["Estado"].isin(list(ESTADOS)), "Nueva")
        columnas = st.columns(len(ESTADOS), gap="small")
        for col, (nombre, color) in zip(columnas, ESTADOS.items()):
            grupo = guardadas[est == nombre]
            with col:
                st.markdown(
                    f'<div class="colhead"><span><span class="dot" style="background:{color}"></span>{nombre}</span>'
                    f'<span class="mono">{len(grupo)}</span></div>',
                    unsafe_allow_html=True,
                )
                for _, r in grupo.iterrows():
                    nota = f'<div class="n">{esc(r["Notas"])}</div>' if r["Notas"] else ""
                    fecha_txt = f'Aplicada {r["Aplicada"]}' if r["Aplicada"] else f'Guardada {r["Guardada"]}'
                    st.markdown(
                        f'<div class="kcard"><div class="t">{esc(r["Puesto"])}</div>'
                        f'<div class="c">{esc(r["Empresa"])}</div><div class="mono">{esc(fecha_txt)}</div>{nota}</div>',
                        unsafe_allow_html=True,
                    )
                    if st.button("Ver detalle", key=f"det_{r['ID']}", use_container_width=True):
                        detalle(r["ID"])


# ===========================================================================
# PESTAÑA: TICKETS (igual que antes)
# ===========================================================================
T_HOJA = "Tickets"
T_COLS = ["ID", "Descripción", "Estado", "Prioridad", "Fecha"]
T_ESTADOS = ["Abierto", "En progreso", "Cerrado"]
T_PRIOR = ["Alta", "Media", "Baja"]


def cargar_tickets() -> pd.DataFrame:
    df = conn.read(worksheet=T_HOJA, ttl=0).dropna(how="all")
    for c in T_COLS:
        if c not in df.columns:
            df[c] = None
    df = df[T_COLS].copy()
    df["ID"] = df["ID"].astype(str)
    df["Fecha"] = pd.to_datetime(df["Fecha"], errors="coerce").dt.date
    return df


def guardar_tickets(df: pd.DataFrame) -> None:
    out = df.copy()
    out["Fecha"] = pd.to_datetime(out["Fecha"]).dt.strftime("%Y-%m-%d")
    conn.update(worksheet=T_HOJA, data=out)


with tab_tickets:
    st.markdown('<div class="titulo">Tickets de soporte</div>', unsafe_allow_html=True)
    tdf = cargar_tickets()

    with st.form("nuevo_ticket", clear_on_submit=True):
        desc = st.text_area("Describe el problema")
        prio = st.selectbox("Prioridad", T_PRIOR)
        if st.form_submit_button("Enviar", type="primary"):
            if desc.strip():
                nums = pd.to_numeric(tdf["ID"].str.split("-").str[-1], errors="coerce").dropna()
                nid = f"TICKET-{(int(nums.max()) if not nums.empty else 1000) + 1}"
                nuevo = pd.DataFrame([{"ID": nid, "Descripción": desc.strip(), "Estado": "Abierto",
                                       "Prioridad": prio, "Fecha": datetime.date.today()}])
                guardar_tickets(pd.concat([nuevo, tdf], ignore_index=True))
                st.session_state.mensaje = f"Ticket {nid} guardado"
                st.rerun()
            else:
                st.warning("Escribe una descripción antes de enviar.")

    editado = st.data_editor(
        tdf, use_container_width=True, hide_index=True, key="editor_tickets",
        column_config={
            "Estado": st.column_config.SelectboxColumn("Estado", options=T_ESTADOS, required=True),
            "Prioridad": st.column_config.SelectboxColumn("Prioridad", options=T_PRIOR, required=True),
            "Fecha": st.column_config.DateColumn("Fecha", format="YYYY-MM-DD"),
        },
        disabled=["ID", "Fecha"],
    )
    if st.button("Guardar cambios", type="primary", disabled=editado.equals(tdf), key="guardar_tickets"):
        guardar_tickets(editado)
        st.session_state.mensaje = "Cambios guardados"
        st.rerun()

    if not editado.empty:
        g = editado.copy()
        g["Fecha"] = pd.to_datetime(g["Fecha"])
        st.altair_chart(
            alt.Chart(g).mark_bar().encode(
                x=alt.X("yearmonth(Fecha):O", title="Mes"), y=alt.Y("count():Q", title="Tickets"),
                xOffset="Estado:N", color=alt.Color("Estado:N", sort=T_ESTADOS),
            ).configure_legend(orient="bottom"),
            use_container_width=True,
        )
