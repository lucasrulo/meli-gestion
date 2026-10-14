from datetime import datetime

import streamlit as st

from meli import promos
from meli.api import MeliError
from meli.bulk import run_bulk
from meli.excel import to_number
from meli.carga import compute_promo, grid_block, mode_picker, preview, resolve
from meli.credibilidad import render_last, save_run
from meli.ui import catalog_index, pick_account

st.session_state["_page"] = "cargar"
st.title("🏷️ Cargar a campaña")
st.caption("Suma o quita modelos-color de una campaña propia o una campaña tradicional de MeLi. "
           "Para descuentos sueltos por producto usá **Descuentos**.")
client = pick_account()

key = f"promos_{client.user_id}"
if key not in st.session_state:
    try:
        with st.spinner("Leyendo promociones…"):
            st.session_state[key] = promos.list_promotions(client)
    except MeliError as e:
        st.error(str(e))
        st.stop()

choices = [p for p in st.session_state[key]
           if p.get("type") in {"SELLER_CAMPAIGN", "DEAL"} and p.get("status") in {"started", "pending", None}]
if not choices:
    st.info("No hay campañas propias ni tradicionales vigentes. Creá una en **Campañas**.")
    st.stop()

c1, c2 = st.columns([3, 1])
i = c1.selectbox(
    "Campaña",
    range(len(choices)),
    format_func=lambda k: f"{choices[k].get('name')} · {promos.TYPE_LABELS.get(choices[k]['type'])} · "
                          f"{choices[k].get('status')} · {str(choices[k].get('start_date', ''))[:10]} → "
                          f"{str(choices[k].get('finish_date', ''))[:10]}",
)
accion = c2.radio("Acción", ["Agregar", "Quitar"], horizontal=True)
target = choices[i]
quitar = accion == "Quitar"

mode = mode_picker("cargar")
index = catalog_index(client)
data = grid_block("lista" if quitar else "promo", "cargar", index, mode)
if data is None:
    st.stop()

st.divider()
st.subheader("Vista previa")
det = compute_promo(resolve(index, data, mode), True, quitar)
todo = preview(det, "cargar", "dto_%")
if todo.empty:
    st.info("No hay nada para procesar.")
    st.stop()

st.divider()
ok = st.checkbox(f"Confirmo {accion.lower()} {len(todo)} publicaciones en «{target['name']}»")
if st.button(f"🚀 {accion} {len(todo)} publicaciones", type="primary", disabled=not ok):
    def job(r):
        if quitar:
            promos.remove_item(client, r["item_id"], target["type"], target["id"])
        else:
            promos.add_item(client, r["item_id"], target["type"], target["id"], deal_price=r["precio_nuevo"],
                            top_deal_price=to_number(r.get("precio_meli_plus")))

    res = run_bulk(todo.to_dict("records"), job, label=accion)
    save_run("cargar", res, client, target["type"], target["id"])

render_last(client, "cargar", f"resultado_campana_{datetime.now():%Y%m%d_%H%M}.xlsx",
            ["clave", "item_id", "titulo", "precio_lista", "precio_nuevo", "dto_%"])
