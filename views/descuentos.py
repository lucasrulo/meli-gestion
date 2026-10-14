from datetime import date, datetime, time, timedelta

import streamlit as st

from meli import promos
from meli.api import MeliError
from meli.bulk import run_bulk
from meli.carga import compute_promo, grid_block, mode_picker, preview, resolve
from meli.credibilidad import render_last, save_run
from meli.ui import catalog_index, pick_account

st.session_state["_page"] = "descuentos"
st.title("🔖 Descuentos masivos")
client = pick_account()

pkey = f"promos_{client.user_id}"


def load_promos(force=False):
    if force or pkey not in st.session_state:
        with st.spinner("Leyendo descuentos existentes…"):
            st.session_state[pkey] = promos.list_promotions(client)
    return st.session_state[pkey]


try:
    existentes = [p for p in load_promos() if p.get("type") == "SELLER_CAMPAIGN"
                  and p.get("status") in {"started", "pending", None}]
except MeliError as e:
    st.error(str(e))
    st.stop()

accion = st.radio("Acción", ["Aplicar descuento", "Quitar descuento"], horizontal=True)
quitar = accion.startswith("Quitar")

# ---------------- Descuento (nombre) ----------------
NUEVO = "➕ Nuevo descuento"
SIN_NOMBRE = "Sin nombre (descuento individual por producto)"
opciones = ([] if quitar else [NUEVO]) + [p["id"] for p in existentes] + [SIN_NOMBRE]
by_id = {p["id"]: p for p in existentes}
sel = st.selectbox(
    "Descuento",
    opciones,
    format_func=lambda o: o if o in (NUEVO, SIN_NOMBRE) else
    f"{by_id[o].get('name')} · {by_id[o].get('status')} · "
    f"{str(by_id[o].get('start_date', ''))[:10]} → {str(by_id[o].get('finish_date', ''))[:10]}",
    help="Con nombre queda como promoción propia en MeLi (Central de promociones) con ese nombre. "
         "Sin nombre usa el descuento individual por producto.",
    key="desc_sel",
)

nombre = None
start = finish = None
if sel == NUEVO:
    nombre = st.text_input("Nombre del descuento", placeholder="Ej: Kappa Botines -20% Octubre", max_chars=60,
                           key="desc_nombre")
if not quitar and sel in (NUEVO, SIN_NOMBRE):
    c1, c2, c3, c4 = st.columns(4)
    d1 = c1.date_input("Desde", date.today(), format="DD/MM/YYYY")
    t1 = c2.time_input("Hora inicio", time(0, 0))
    d2 = c3.date_input("Hasta", date.today() + timedelta(days=7), format="DD/MM/YYYY")
    t2 = c4.time_input("Hora fin", time(23, 59))
    start = datetime.combine(d1, t1)
    if start < datetime.now():
        start = datetime.now() + timedelta(minutes=10)
    finish = datetime.combine(d2, t2).replace(second=59)
    if finish <= start:
        st.error("La fecha de fin tiene que ser posterior al inicio.")
        st.stop()
    st.caption(f"Vigencia: {start:%d/%m/%Y %H:%M} → {finish:%d/%m/%Y %H:%M}. MeLi valida la duración máxima permitida.")
elif sel in by_id:
    p = by_id[sel]
    st.caption(f"Vigencia del descuento: {str(p.get('start_date', ''))[:16].replace('T', ' ')} → "
               f"{str(p.get('finish_date', ''))[:16].replace('T', ' ')}")

if st.button("🔄 Actualizar lista de descuentos"):
    load_promos(force=True)
    st.rerun()

# ---------------- Productos ----------------
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

if sel == NUEVO and not (nombre or "").strip():
    st.warning("Poné un nombre al descuento para continuar.")
    st.stop()

etiqueta = (nombre.strip() if sel == NUEVO else "(sin nombre)" if sel == SIN_NOMBRE else by_id[sel].get("name"))
st.divider()
ok = st.checkbox(f"Confirmo {'quitar' if quitar else 'aplicar'} el descuento «{etiqueta}» "
                 f"{'de' if quitar else 'a'} {len(todo)} publicaciones ({todo['clave'].nunique()} modelos-color)")
if st.button(f"🚀 {accion} ({len(todo)})", type="primary", disabled=not ok):
    promo_id, ptype = None, "PRICE_DISCOUNT"
    if sel == NUEVO:
        try:
            r = promos.create_seller_campaign(client, nombre.strip(), start, finish)
            promo_id, ptype = r.get("id"), "SELLER_CAMPAIGN"
            st.success(f"Descuento creado en MeLi: {r.get('name') or nombre} ({promo_id})")
            load_promos(force=True)
        except MeliError as e:
            st.error(f"No se pudo crear el descuento: {e}")
            st.stop()
    elif sel in by_id:
        promo_id, ptype = sel, "SELLER_CAMPAIGN"

    def job(r):
        if quitar:
            promos.remove_item(client, r["item_id"], ptype, promo_id)
        elif ptype == "PRICE_DISCOUNT":
            promos.add_item(client, r["item_id"], ptype, deal_price=r["precio_nuevo"], start=start, finish=finish)
        else:
            promos.add_item(client, r["item_id"], ptype, promo_id, deal_price=r["precio_nuevo"])

    res = run_bulk(todo.to_dict("records"), job, label=accion)
    res.insert(0, "descuento", etiqueta)
    save_run("desc", res, client, ptype, promo_id, start, finish)
    st.cache_data.clear()

render_last(client, "desc", f"resultado_descuentos_{datetime.now():%Y%m%d_%H%M}.xlsx",
            ["descuento", "clave", "item_id", "titulo", "precio_lista", "precio_nuevo", "dto_%"])
