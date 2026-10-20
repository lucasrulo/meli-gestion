from datetime import datetime

import streamlit as st

from meli.theme import hero

from meli.bulk import run_bulk
from meli.carga import compute_precio, grid_block, mode_picker, preview, resolve
from meli.prices import update_price
from meli.ui import catalog_index, pick_account, show_results

st.session_state["_page"] = "precios"
hero("Precios masivos", "Actualizá precios por modelo-color con vista previa, % masivos y redondeo inteligente.", "PRECIOS")
client = pick_account()

c1, c2 = st.columns([3, 1])
with c1:
    mode = mode_picker("precios")
alert = c2.number_input("Alertar si cambia más de %", 1, 300, 50)

index = catalog_index(client)
data = grid_block("precio", "precios", index, mode)
if data is None:
    st.stop()

st.divider()
st.subheader("Vista previa")
det = compute_precio(resolve(index, data, mode), True, alert)
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
