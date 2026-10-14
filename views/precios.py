from datetime import datetime

import streamlit as st

from meli.bulk import run_bulk
from meli.carga import compute_precio, input_block, mode_picker, preview, resolve
from meli.prices import update_price
from meli.ui import catalog_index, pick_account, show_results

st.session_state["_page"] = "precios"
st.title("💲 Precios masivos")
client = pick_account()

data = input_block("precio", "precios")
c1, c2, c3 = st.columns([2, 1, 1])
with c1:
    mode = mode_picker("precios")
round_int = c2.checkbox("Redondear a entero", value=True)
alert = c3.number_input("Alertar si cambia más de %", 1, 100, 30)

if data is None:
    st.stop()
if "precio" not in data:
    st.error("Falta la columna precio.")
    st.stop()

index = catalog_index(client)
det = compute_precio(resolve(index, data, mode), round_int, alert)
todo = preview(det, "precios", "var_%")

if todo.empty:
    st.info("No hay nada para actualizar.")
    st.stop()

st.divider()
ok = st.checkbox(f"Confirmo cambiar el precio de {len(todo)} publicaciones ({todo['clave'].nunique()} modelos-color)")
if st.button(f"🚀 Actualizar {len(todo)} publicaciones", type="primary", disabled=not ok):
    res = run_bulk(todo.to_dict("records"),
                   lambda r: update_price(client, r["item_id"], r["precio_nuevo"], r.get("variation_ids")),
                   label="Actualizando precios")
    keep = [c for c in ["clave", "item_id", "titulo", "precio_lista", "precio_nuevo", "var_%", "resultado", "error",
                        "procesado"] if c in res]
    show_results(res[keep], f"resultado_precios_{datetime.now():%Y%m%d_%H%M}.xlsx")
    st.cache_data.clear()
