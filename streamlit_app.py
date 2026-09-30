import datetime

import altair as alt
import pandas as pd
import streamlit as st
from streamlit_gsheets import GSheetsConnection

st.set_page_config(page_title="Tickets de soporte", page_icon="🎫")
st.title("🎫 Tickets de soporte")
st.write("Los tickets se guardan en Google Sheets, así que no se pierden al recargar.")

# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------
WORKSHEET = "Tickets"  # Nombre de la pestaña en tu Google Sheet
COLUMNS = ["ID", "Descripción", "Estado", "Prioridad", "Fecha"]
ESTADOS = ["Abierto", "En progreso", "Cerrado"]
PRIORIDADES = ["Alta", "Media", "Baja"]

conn = st.connection("gsheets", type=GSheetsConnection)


# ---------------------------------------------------------------------------
# Leer y guardar en Google Sheets
# ---------------------------------------------------------------------------
def cargar_tickets() -> pd.DataFrame:
    """Lee la hoja y la devuelve limpia. ttl=0 para leer siempre lo más reciente."""
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
    """Sobrescribe la hoja con el DataFrame completo."""
    salida = df.copy()
    salida["Fecha"] = pd.to_datetime(salida["Fecha"]).dt.strftime("%Y-%m-%d")
    conn.update(worksheet=WORKSHEET, data=salida)


def siguiente_id(df: pd.DataFrame) -> str:
    """Calcula el siguiente ID de forma numérica (TICKET-1001, TICKET-1002, ...)."""
    numeros = pd.to_numeric(df["ID"].str.split("-").str[-1], errors="coerce").dropna()
    ultimo = int(numeros.max()) if not numeros.empty else 1000
    return f"TICKET-{ultimo + 1}"


# Mensaje pendiente de una acción anterior (sobrevive al st.rerun)
if "mensaje" in st.session_state:
    st.success(st.session_state.pop("mensaje"))

df = cargar_tickets()

# ---------------------------------------------------------------------------
# Agregar ticket
# ---------------------------------------------------------------------------
st.header("Agregar un ticket")

with st.form("nuevo_ticket", clear_on_submit=True):
    descripcion = st.text_area("Describe el problema")
    prioridad = st.selectbox("Prioridad", PRIORIDADES)
    enviado = st.form_submit_button("Enviar")

if enviado:
    if not descripcion.strip():
        st.warning("Escribe una descripción antes de enviar.")
    else:
        nuevo = pd.DataFrame(
            [{
                "ID": siguiente_id(df),
                "Descripción": descripcion.strip(),
                "Estado": "Abierto",
                "Prioridad": prioridad,
                "Fecha": datetime.date.today(),
            }]
        )
        guardar_tickets(pd.concat([nuevo, df], ignore_index=True))
        st.session_state.mensaje = f"Ticket {nuevo.loc[0, 'ID']} guardado."
        st.rerun()

# ---------------------------------------------------------------------------
# Ver y editar tickets
# ---------------------------------------------------------------------------
st.header("Tickets existentes")
st.write(f"Número de tickets: `{len(df)}`")
st.info("Haz doble clic en una celda para editar y luego presiona **Guardar cambios**.", icon="✍️")

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
    key="editor",
)

hay_cambios = not editado.equals(df)
if st.button("Guardar cambios", type="primary", disabled=not hay_cambios):
    guardar_tickets(editado)
    st.session_state.mensaje = "Cambios guardados en Google Sheets."
    st.rerun()

# ---------------------------------------------------------------------------
# Estadísticas (calculadas con los datos reales)
# ---------------------------------------------------------------------------
st.header("Estadísticas")

col1, col2, col3 = st.columns(3)
col1.metric("Abiertos", int((editado["Estado"] == "Abierto").sum()))
col2.metric("En progreso", int((editado["Estado"] == "En progreso").sum()))
col3.metric("Cerrados", int((editado["Estado"] == "Cerrado").sum()))

if editado.empty:
    st.caption("Aún no hay tickets para graficar.")
else:
    graf = editado.copy()
    graf["Fecha"] = pd.to_datetime(graf["Fecha"])

    st.write("##### Tickets por estado y mes")
    st.altair_chart(
        alt.Chart(graf)
        .mark_bar()
        .encode(
            x=alt.X("yearmonth(Fecha):O", title="Mes"),
            y=alt.Y("count():Q", title="Tickets"),
            xOffset="Estado:N",
            color=alt.Color("Estado:N", sort=ESTADOS),
        )
        .configure_legend(orient="bottom"),
        use_container_width=True,
    )

    st.write("##### Prioridades actuales")
    st.altair_chart(
        alt.Chart(graf)
        .mark_arc()
        .encode(theta="count():Q", color=alt.Color("Prioridad:N", sort=PRIORIDADES))
        .properties(height=300)
        .configure_legend(orient="bottom"),
        use_container_width=True,
    )
