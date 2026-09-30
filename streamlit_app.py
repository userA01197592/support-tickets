import datetime
from urllib.parse import urlencode

import altair as alt
import pandas as pd
import streamlit as st
from apify_client import ApifyClient
from streamlit_gsheets import GSheetsConnection

st.set_page_config(page_title="Mi panel", page_icon="💼", layout="wide")

conn = st.connection("gsheets", type=GSheetsConnection)

# Mensaje pendiente de una acción anterior (sobrevive al st.rerun)
if "mensaje" in st.session_state:
    st.success(st.session_state.pop("mensaje"))

tab_vacantes, tab_tickets = st.tabs(["💼 Buscar empleo", "🎫 Tickets"])


# ===========================================================================
# PESTAÑA 1: BÚSQUEDA DE EMPLEO (LinkedIn vía Apify)
# ===========================================================================
ACTOR_ID = "curious_coder/linkedin-jobs-scraper"  # <- el scraper que se usa
HOJA_VACANTES = "Vacantes"
COLS_VAC = ["ID", "Puesto", "Empresa", "Ubicación", "Publicada", "Link", "Estado", "Notas", "Guardada"]
ESTADOS_VAC = ["Nueva", "Aplicada", "Entrevista", "Oferta", "Descartada"]
FECHAS = {
    "Últimas 24 horas": "r86400",
    "Última semana": "r604800",
    "Último mes": "r2592000",
    "Cualquier fecha": "",
}


def primero(item: dict, *claves):
    """Devuelve el primer campo que exista en el resultado (los nombres varían)."""
    for c in claves:
        v = item.get(c)
        if v not in (None, "", []):
            return v
    return ""


def buscar_vacantes(puesto: str, ubicacion: str, fecha: str, limite: int) -> pd.DataFrame:
    params = {"keywords": puesto, "location": ubicacion}
    if fecha:
        params["f_TPR"] = fecha
    url = "https://www.linkedin.com/jobs/search/?" + urlencode(params)

    client = ApifyClient(st.secrets["APIFY_TOKEN"])
    run = client.actor(ACTOR_ID).call(
        run_input={"urls": [url], "limitPerSource": limite, "count": limite},
        timeout_secs=300,
    )
    if run is None:
        raise RuntimeError("Apify no devolvió resultados.")

    filas = []
    for item in client.dataset(run["defaultDatasetId"]).iterate_items():
        link = primero(item, "link", "jobUrl", "url", "applyUrl")
        filas.append({
            "Guardar": False,
            "ID": str(primero(item, "id", "jobId") or link),
            "Puesto": primero(item, "title", "jobTitle", "position"),
            "Empresa": primero(item, "companyName", "company"),
            "Ubicación": primero(item, "location", "jobLocation"),
            "Publicada": str(primero(item, "postedAt", "publishedAt", "listedAt", "postedTime"))[:10],
            "Link": link,
        })
    return pd.DataFrame(filas).head(limite)


def cargar_vacantes() -> pd.DataFrame:
    try:
        df = conn.read(worksheet=HOJA_VACANTES, ttl=0)
    except Exception:
        # Si la pestaña no existe, la crea automáticamente
        df = pd.DataFrame(columns=COLS_VAC)
        conn.create(worksheet=HOJA_VACANTES, data=df)
    df = df.dropna(how="all")
    for c in COLS_VAC:
        if c not in df.columns:
            df[c] = ""
    df = df[COLS_VAC].fillna("").astype(str)
    return df


def guardar_vacantes(df: pd.DataFrame) -> None:
    conn.update(worksheet=HOJA_VACANTES, data=df[COLS_VAC])


with tab_vacantes:
    st.title("💼 Buscar empleo en LinkedIn")

    if "APIFY_TOKEN" not in st.secrets:
        st.error("Falta `APIFY_TOKEN` en los Secrets de la app.")
        st.stop()

    # --- Formulario de búsqueda ---
    with st.form("busqueda"):
        c1, c2 = st.columns(2)
        puesto = c1.text_input("Puesto o palabras clave", placeholder="supply chain planner")
        ubicacion = c2.text_input("Ubicación", value="Mexico")
        c3, c4 = st.columns(2)
        fecha = c3.selectbox("Publicadas en", list(FECHAS.keys()), index=1)
        limite = c4.slider("Máximo de vacantes", 10, 100, 25, step=5)
        st.caption(f"Costo aproximado: hasta ${limite * 0.002:.2f} USD por búsqueda (de tu crédito gratis de Apify).")
        buscar = st.form_submit_button("🔍 Buscar", type="primary")

    if buscar:
        if not puesto.strip():
            st.warning("Escribe un puesto o palabra clave.")
        else:
            with st.spinner("Buscando en LinkedIn... (puede tardar 1-2 minutos)"):
                try:
                    st.session_state.resultados = buscar_vacantes(
                        puesto.strip(), ubicacion.strip(), FECHAS[fecha], limite
                    )
                except Exception as e:
                    st.error(f"Error al buscar: {e}")

    guardadas = cargar_vacantes()

    # --- Resultados de la búsqueda ---
    res = st.session_state.get("resultados")
    if res is not None:
        st.subheader(f"Resultados ({len(res)})")
        if res.empty:
            st.info("No se encontraron vacantes. Prueba con otras palabras o una ubicación más amplia.")
        else:
            res = res.copy()
            res["Ya guardada"] = res["ID"].isin(guardadas["ID"])
            sel = st.data_editor(
                res,
                hide_index=True,
                use_container_width=True,
                column_config={
                    "Guardar": st.column_config.CheckboxColumn("Guardar"),
                    "Link": st.column_config.LinkColumn("Link", display_text="Abrir"),
                    "ID": None,
                },
                disabled=[c for c in res.columns if c != "Guardar"],
                key="editor_resultados",
            )
            b1, b2 = st.columns(2)
            guardar_sel = b1.button("💾 Guardar seleccionadas")
            guardar_todas = b2.button("💾 Guardar todas")

            if guardar_sel or guardar_todas:
                nuevas = sel if guardar_todas else sel[sel["Guardar"]]
                nuevas = nuevas[~nuevas["ID"].isin(guardadas["ID"])].copy()
                if nuevas.empty:
                    st.info("No hay vacantes nuevas para guardar.")
                else:
                    nuevas["Estado"] = "Nueva"
                    nuevas["Notas"] = ""
                    nuevas["Guardada"] = datetime.date.today().isoformat()
                    guardar_vacantes(pd.concat([nuevas[COLS_VAC], guardadas], ignore_index=True))
                    st.session_state.mensaje = f"{len(nuevas)} vacante(s) guardada(s) en Google Sheets."
                    st.rerun()

    # --- Seguimiento de vacantes guardadas ---
    st.divider()
    st.subheader(f"📋 Mis vacantes ({len(guardadas)})")
    if guardadas.empty:
        st.caption("Aún no has guardado vacantes.")
    else:
        m = st.columns(len(ESTADOS_VAC))
        for col, est in zip(m, ESTADOS_VAC):
            col.metric(est, int((guardadas["Estado"] == est).sum()))

        editadas = st.data_editor(
            guardadas,
            hide_index=True,
            use_container_width=True,
            column_config={
                "Estado": st.column_config.SelectboxColumn("Estado", options=ESTADOS_VAC, required=True),
                "Notas": st.column_config.TextColumn("Notas", width="medium"),
                "Link": st.column_config.LinkColumn("Link", display_text="Abrir"),
                "ID": None,
            },
            disabled=["Puesto", "Empresa", "Ubicación", "Publicada", "Link", "Guardada"],
            key="editor_vacantes",
        )
        if st.button("Guardar cambios de seguimiento", type="primary",
                     disabled=editadas.equals(guardadas)):
            guardar_vacantes(editadas)
            st.session_state.mensaje = "Seguimiento actualizado."
            st.rerun()


# ===========================================================================
# PESTAÑA 2: TICKETS (igual que antes)
# ===========================================================================
WORKSHEET = "Tickets"
COLUMNS = ["ID", "Descripción", "Estado", "Prioridad", "Fecha"]
ESTADOS = ["Abierto", "En progreso", "Cerrado"]
PRIORIDADES = ["Alta", "Media", "Baja"]


def cargar_tickets() -> pd.DataFrame:
    df = conn.read(worksheet=WORKSHEET, ttl=0)
    df = df.dropna(how="all")
    for col in COLUMNS:
        if col not in df.columns:
            df[col] = None
    df = df[COLUMNS].copy()
    df["ID"] = df["ID"].astype(str)
    df["Fecha"] = pd.to_datetime(df["Fecha"], errors="coerce").dt.date
    return df


def guardar_tickets(df: pd.DataFrame) -> None:
    salida = df.copy()
    salida["Fecha"] = pd.to_datetime(salida["Fecha"]).dt.strftime("%Y-%m-%d")
    conn.update(worksheet=WORKSHEET, data=salida)


def siguiente_id(df: pd.DataFrame) -> str:
    numeros = pd.to_numeric(df["ID"].str.split("-").str[-1], errors="coerce").dropna()
    ultimo = int(numeros.max()) if not numeros.empty else 1000
    return f"TICKET-{ultimo + 1}"


with tab_tickets:
    st.title("🎫 Tickets de soporte")
    df = cargar_tickets()

    st.header("Agregar un ticket")
    with st.form("nuevo_ticket", clear_on_submit=True):
        descripcion = st.text_area("Describe el problema")
        prioridad = st.selectbox("Prioridad", PRIORIDADES)
        enviado = st.form_submit_button("Enviar")

    if enviado:
        if not descripcion.strip():
            st.warning("Escribe una descripción antes de enviar.")
        else:
            nuevo = pd.DataFrame([{
                "ID": siguiente_id(df),
                "Descripción": descripcion.strip(),
                "Estado": "Abierto",
                "Prioridad": prioridad,
                "Fecha": datetime.date.today(),
            }])
            guardar_tickets(pd.concat([nuevo, df], ignore_index=True))
            st.session_state.mensaje = f"Ticket {nuevo.loc[0, 'ID']} guardado."
            st.rerun()

    st.header("Tickets existentes")
    st.write(f"Número de tickets: `{len(df)}`")
    editado = st.data_editor(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Estado": st.column_config.SelectboxColumn("Estado", options=ESTADOS, required=True),
            "Prioridad": st.column_config.SelectboxColumn("Prioridad", options=PRIORIDADES, required=True),
            "Fecha": st.column_config.DateColumn("Fecha", format="YYYY-MM-DD"),
        },
        disabled=["ID", "Fecha"],
        key="editor_tickets",
    )
    if st.button("Guardar cambios", type="primary", disabled=editado.equals(df)):
        guardar_tickets(editado)
        st.session_state.mensaje = "Cambios guardados en Google Sheets."
        st.rerun()

    st.header("Estadísticas")
    c1, c2, c3 = st.columns(3)
    c1.metric("Abiertos", int((editado["Estado"] == "Abierto").sum()))
    c2.metric("En progreso", int((editado["Estado"] == "En progreso").sum()))
    c3.metric("Cerrados", int((editado["Estado"] == "Cerrado").sum()))

    if not editado.empty:
        graf = editado.copy()
        graf["Fecha"] = pd.to_datetime(graf["Fecha"])
        st.altair_chart(
            alt.Chart(graf).mark_bar().encode(
                x=alt.X("yearmonth(Fecha):O", title="Mes"),
                y=alt.Y("count():Q", title="Tickets"),
                xOffset="Estado:N",
                color=alt.Color("Estado:N", sort=ESTADOS),
            ).configure_legend(orient="bottom"),
            use_container_width=True,
        )
