from datetime import date, datetime, time, timedelta

import pandas as pd
import streamlit as st

from meli import promos
from meli.api import MeliError
from meli.bulk import run_bulk
from meli.catalog import match
from meli.excel import read_excel, template, to_number
from meli.ui import catalog_index, pick_account, show_results

st.session_state["_page"] = "cargar"
st.title("🏷️ Cargar SKUs a una promoción")
client = pick_account()

# ---------- Destino ----------
key = f"promos_{client.user_id}"
if key not in st.session_state:
    try:
        with st.spinner("Leyendo promociones…"):
            st.session_state[key] = promos.list_promotions(client)
    except MeliError as e:
        st.error(str(e))
        st.stop()

valid = [p for p in st.session_state[key]
         if p.get("type") in {"SELLER_CAMPAIGN", "DEAL"} and p.get("status") in {"started", "pending", None}]
DISCOUNT = {"id": None, "type": "PRICE_DISCOUNT", "name": "Descuento individual por item (sin campaña)"}
choices = valid + [DISCOUNT]

c1, c2 = st.columns([3, 1])
idx = c1.selectbox(
    "Promoción destino",
    range(len(choices)),
    format_func=lambda i: f"{choices[i].get('name')} · {promos.TYPE_LABELS.get(choices[i]['type'])}"
                          + (f" · {choices[i].get('status')} · {str(choices[i].get('start_date', ''))[:10]} → "
                             f"{str(choices[i].get('finish_date', ''))[:10]}" if choices[i]['id'] else ""),
)
mode = c2.radio("Acción", ["Agregar", "Quitar"], horizontal=True)
target = choices[idx]

pd_start = pd_end = None
if target["type"] == "PRICE_DISCOUNT":
    a, b = st.columns(2)
    pd_start = datetime.combine(a.date_input("Desde", date.today(), format="DD/MM/YYYY"), time(0, 0))
    pd_end = datetime.combine(b.date_input("Hasta", date.today() + timedelta(days=7), format="DD/MM/YYYY"),
                              time(23, 59, 59))

# ---------- Excel ----------
st.download_button(
    "⬇️ Plantilla Excel",
    template(["sku", "precio_promo", "descuento_pct", "precio_meli_plus"],
             [["ABC123-001", 49999, None, None], ["XYZ987", None, 25, None], ["MLA1234567890", None, 30, None]]),
    file_name="plantilla_promo.xlsx",
    help="Por fila: precio_promo O descuento_pct (sobre el precio sin promo). precio_meli_plus es opcional. "
         "En sku podés poner también el ID de publicación (MLA...).",
)
up = st.file_uploader("Subí el Excel", type=["xlsx", "xls", "csv"])
c1, c2 = st.columns(2)
prefix = c1.checkbox("Coincidir por prefijo",
                     help="Ej: 'CL1234-010' agarra todas las publicaciones cuyos SKU empiezan así (todos los talles).")
round_int = c2.checkbox("Redondear precios a entero", value=True)

if not up:
    st.stop()

raw = read_excel(up)
if "sku" not in raw and "item_id" not in raw:
    st.error("El Excel necesita una columna 'sku' (o 'item_id').")
    st.stop()
keycol = "sku" if "sku" in raw else "item_id"

index = catalog_index(client)
m = match(index, raw[keycol], prefix=prefix)
raw["_k"] = raw[keycol].astype(str).str.strip()
m["_k"] = m["clave"].astype(str).str.strip()
df = m.merge(raw.drop_duplicates("_k"), on="_k", how="left")


def compute(r):
    if not r.get("item_id"):
        return pd.Series({"precio_base": None, "deal_price": None, "dto_%": None, "valido": False,
                          "obs": "SKU/ID no encontrado en publicaciones activas/pausadas"})
    base = to_number(r.get("precio_original")) or to_number(r.get("precio_actual"))
    if mode == "Quitar":
        return pd.Series({"precio_base": base, "deal_price": None, "dto_%": None, "valido": True, "obs": ""})
    pp, pct = to_number(r.get("precio_promo")), to_number(r.get("descuento_pct"))
    if pp is None and pct is not None and base:
        pp = base * (1 - pct / 100)
    if pp is None:
        return pd.Series({"precio_base": base, "deal_price": None, "dto_%": None, "valido": False,
                          "obs": "Falta precio_promo o descuento_pct"})
    pp = round(pp) if round_int else round(pp, 2)
    dto = round((1 - pp / base) * 100, 1) if base else None
    obs, ok = "", True
    if base and pp >= base:
        obs, ok = "Precio promo ≥ precio base", False
    elif dto is not None and dto < 5:
        obs = "⚠️ Descuento < 5%: MeLi puede rechazarlo"
    elif dto is not None and dto > 70:
        obs = "⚠️ Descuento > 70%: revisá"
    return pd.Series({"precio_base": base, "deal_price": pp, "dto_%": dto, "valido": ok, "obs": obs})


df = pd.concat([df, df.apply(compute, axis=1)], axis=1)
dups = df["item_id"].notna() & df.duplicated("item_id")
df.loc[dups, ["valido", "obs"]] = [False, "Item repetido (ya está en otra fila)"]

show = ["clave", "item_id", "titulo", "estado", "precio_base", "deal_price", "dto_%", "precio_meli_plus", "valido", "obs"]
show = [c for c in show if c in df]
st.subheader("Vista previa")
v1, v2, v3 = st.columns(3)
v1.metric("Filas Excel", len(raw))
v2.metric("Publicaciones a procesar", int(df["valido"].sum()))
v3.metric("Con problemas", int((~df["valido"]).sum()))
edited = st.data_editor(df[show], width="stretch", hide_index=True,
                        disabled=[c for c in show if c != "valido"], key="prev_promo")

todo = df[edited["valido"].values].to_dict("records")
if not todo:
    st.stop()

ok = st.checkbox(f"Confirmo {mode.lower()} {len(todo)} publicaciones en «{target['name']}»")
if st.button(f"🚀 {mode} {len(todo)} publicaciones", type="primary", disabled=not ok):
    def job(r):
        if mode == "Quitar":
            promos.remove_item(client, r["item_id"], target["type"], target["id"])
        else:
            promos.add_item(client, r["item_id"], target["type"], target["id"],
                            deal_price=r["deal_price"],
                            top_deal_price=to_number(r.get("precio_meli_plus")),
                            start=pd_start, finish=pd_end)

    res = run_bulk(todo, job, label=mode)
    keep = [c for c in ["clave", "item_id", "titulo", "precio_base", "deal_price", "dto_%", "resultado", "error", "procesado"] if c in res]
    show_results(res[keep], f"resultado_promo_{datetime.now():%Y%m%d_%H%M}.xlsx")
