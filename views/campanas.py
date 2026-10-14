from datetime import date, datetime, time, timedelta

import pandas as pd
import streamlit as st

from meli import promos
from meli.api import MeliError
from meli.excel import to_xlsx
from meli.ui import pick_account

st.title("📣 Campañas")
client = pick_account()


def load_promos(force=False):
    key = f"promos_{client.user_id}"
    if force or key not in st.session_state:
        with st.spinner("Leyendo promociones…"):
            st.session_state[key] = promos.list_promotions(client)
    return st.session_state[key]


if st.button("🔄 Actualizar lista"):
    load_promos(force=True)

try:
    data = load_promos()
except MeliError as e:
    st.error(f"Error leyendo promociones: {e}")
    st.stop()

df = pd.DataFrame(data)
if not df.empty:
    df["tipo"] = df["type"].map(lambda t: promos.TYPE_LABELS.get(t, t))
    cols = [c for c in ["id", "tipo", "type", "name", "status", "start_date", "finish_date", "deadline_date"] if c in df]
    f1, f2 = st.columns(2)
    tipos = f1.multiselect("Tipo", sorted(df["tipo"].unique()))
    estados = f2.multiselect("Estado", sorted(df["status"].dropna().unique()) if "status" in df else [])
    view = df
    if tipos:
        view = view[view["tipo"].isin(tipos)]
    if estados:
        view = view[view["status"].isin(estados)]
    st.dataframe(view[cols], width="stretch", hide_index=True)
else:
    st.info("La cuenta no tiene promociones.")

# ---------------- Crear ----------------
st.divider()
st.subheader("➕ Crear campaña propia")
st.caption("Campaña del vendedor con % flexible: cada SKU lleva su propio precio promo (lo cargás en *Cargar SKUs a promo*). "
           "MeLi valida duración máxima y fechas; si algo no cumple, muestra el error acá.")
with st.form("crear"):
    name = st.text_input("Nombre", placeholder="Hot Sale Columbia")
    c1, c2, c3, c4 = st.columns(4)
    d_start = c1.date_input("Desde", value=date.today() + timedelta(days=1), format="DD/MM/YYYY")
    t_start = c2.time_input("Hora inicio", value=time(0, 0))
    d_end = c3.date_input("Hasta", value=date.today() + timedelta(days=7), format="DD/MM/YYYY")
    t_end = c4.time_input("Hora fin", value=time(23, 59))
    if st.form_submit_button("Crear campaña", type="primary"):
        start = datetime.combine(d_start, t_start)
        finish = datetime.combine(d_end, t_end).replace(second=59)
        if not name.strip():
            st.error("Poné un nombre.")
        elif finish <= start:
            st.error("La fecha de fin tiene que ser posterior al inicio.")
        else:
            try:
                r = promos.create_seller_campaign(client, name.strip(), start, finish)
                st.success(f"Campaña creada: {r.get('id')} · {r.get('name')} · {r.get('status')}")
                load_promos(force=True)
            except MeliError as e:
                st.error(str(e))

# ---------------- Gestionar ----------------
st.divider()
st.subheader("🛠️ Ver / editar una promoción")
if df.empty:
    st.stop()

opts = df.to_dict("records")
sel = st.selectbox(
    "Promoción",
    range(len(opts)),
    format_func=lambda i: f"{opts[i].get('name') or opts[i]['id']} · {promos.TYPE_LABELS.get(opts[i]['type'], opts[i]['type'])} · {opts[i].get('status')}",
)
p = opts[sel]

tab_items, tab_edit = st.tabs(["Items", "Editar / eliminar"])
with tab_items:
    status = st.selectbox("Estado de items", ["started", "pending", "candidate", "(todos)"])
    if st.button("Ver items"):
        try:
            with st.spinner("Leyendo items…"):
                items = promos.promotion_items(client, p["id"], p["type"], None if status == "(todos)" else status)
            idf = pd.DataFrame(items)
            st.write(f"{len(idf)} items")
            st.dataframe(idf, width="stretch", hide_index=True)
            if not idf.empty:
                st.download_button("⬇️ Excel", to_xlsx(idf), file_name=f"items_{p['id']}.xlsx")
        except MeliError as e:
            st.error(str(e))

with tab_edit:
    if p["type"] != "SELLER_CAMPAIGN":
        st.info("Solo se pueden editar/eliminar campañas propias (SELLER_CAMPAIGN).")
    else:
        def _parse(s, fallback):
            try:
                return datetime.fromisoformat(str(s)[:19])
            except Exception:
                return fallback

        s0 = _parse(p.get("start_date"), datetime.now())
        f0 = _parse(p.get("finish_date"), datetime.now() + timedelta(days=7))
        with st.form("editar"):
            new_name = st.text_input("Nombre", value=p.get("name") or "")
            c1, c2, c3, c4 = st.columns(4)
            ds = c1.date_input("Desde", value=s0.date(), format="DD/MM/YYYY")
            ts = c2.time_input("Hora inicio", value=s0.time())
            de = c3.date_input("Hasta", value=f0.date(), format="DD/MM/YYYY")
            te = c4.time_input("Hora fin", value=f0.time())
            if st.form_submit_button("Guardar cambios"):
                try:
                    promos.update_seller_campaign(client, p["id"], new_name,
                                                  datetime.combine(ds, ts), datetime.combine(de, te))
                    st.success("Actualizada")
                    load_promos(force=True)
                except MeliError as e:
                    st.error(str(e))
        st.markdown("---")
        if st.checkbox("Confirmo eliminar esta campaña (saca todos sus items)"):
            if st.button("🗑️ Eliminar campaña"):
                try:
                    promos.delete_promotion(client, p["id"], "SELLER_CAMPAIGN")
                    st.success("Eliminada")
                    load_promos(force=True)
                except MeliError as e:
                    st.error(str(e))
