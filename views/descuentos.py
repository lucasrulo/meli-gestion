from datetime import date, datetime, time, timedelta

import streamlit as st

from meli import promos
from meli.bulk import run_bulk
from meli.carga import compute_promo, grid_block, mode_picker, preview, resolve
from meli.ui import catalog_index, pick_account, show_results

st.session_state["_page"] = "descuentos"
st.title("🔖 Descuentos masivos")
st.caption("Es el **descuento por producto** del panel de MeLi (Promociones → Descuento), aplicado en bloque: "
           "cada publicación queda con su precio tachado y el precio con descuento entre las fechas que elijas.")
client = pick_account()

accion = st.radio("Acción", ["Aplicar descuento", "Quitar descuento"], horizontal=True)
quitar = accion.startswith("Quitar")

start = finish = None
if not quitar:
    c1, c2, c3, c4 = st.columns(4)
    d1 = c1.date_input("Desde", date.today(), format="DD/MM/YYYY")
    t1 = c2.time_input("Hora inicio", time(0, 0))
    d2 = c3.date_input("Hasta", date.today() + timedelta(days=7), format="DD/MM/YYYY")
    t2 = c4.time_input("Hora fin", time(23, 59))
    start = datetime.combine(d1, t1)
    if d1 == date.today() and start < datetime.now():
        start = datetime.now() + timedelta(minutes=5)
    finish = datetime.combine(d2, t2).replace(second=59)
    if finish <= start:
        st.error("La fecha de fin tiene que ser posterior al inicio.")
        st.stop()
    st.caption(f"Vigencia: {start:%d/%m/%Y %H:%M} → {finish:%d/%m/%Y %H:%M}. MeLi valida la duración máxima permitida.")

mode = mode_picker("desc")
index = catalog_index(client)
data = grid_block("lista" if quitar else "promo", "desc", index, mode)
if data is None:
    st.stop()

st.divider()
st.subheader("Vista previa")
det = compute_promo(resolve(index, data, mode), True, quitar)
todo = preview(det, "desc", "dto_%")
if todo.empty:
    st.info("No hay nada para procesar.")
    st.stop()

st.divider()
ok = st.checkbox(f"Confirmo {'quitar el descuento de' if quitar else 'aplicar descuento a'} "
                 f"{len(todo)} publicaciones ({todo['clave'].nunique()} modelos-color)")
if st.button(f"🚀 {accion} ({len(todo)})", type="primary", disabled=not ok):
    def job(r):
        if quitar:
            promos.remove_item(client, r["item_id"], "PRICE_DISCOUNT")
        else:
            promos.add_item(client, r["item_id"], "PRICE_DISCOUNT", deal_price=r["precio_nuevo"],
                            start=start, finish=finish)

    res = run_bulk(todo.to_dict("records"), job, label=accion)
    keep = [c for c in ["clave", "item_id", "titulo", "precio_lista", "precio_nuevo", "dto_%", "resultado", "error",
                        "procesado"] if c in res]
    show_results(res[keep], f"resultado_descuentos_{datetime.now():%Y%m%d_%H%M}.xlsx")
    st.cache_data.clear()
