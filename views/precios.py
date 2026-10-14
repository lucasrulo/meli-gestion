from datetime import datetime

import pandas as pd
import streamlit as st

from meli.bulk import run_bulk
from meli.catalog import match
from meli.excel import read_excel, template, to_number
from meli.prices import update_price
from meli.ui import catalog_index, pick_account, show_results

st.session_state["_page"] = "precios"
st.title("💲 Actualización masiva de precios")
client = pick_account()

st.download_button(
    "⬇️ Plantilla Excel",
    template(["sku", "precio"], [["ABC123-001", 89999], ["MLA1234567890", 45999]]),
    file_name="plantilla_precios.xlsx",
    help="sku (o ID MLA...) + precio nuevo de lista. Si el SKU está en varias publicaciones, se actualizan todas.",
)
up = st.file_uploader("Subí el Excel", type=["xlsx", "xls", "csv"])
c1, c2, c3 = st.columns(3)
prefix = c1.checkbox("Coincidir por prefijo", help="Útil si el Excel tiene SKU por modelo/color y MeLi por talle.")
round_int = c2.checkbox("Redondear a entero", value=True)
alert = c3.number_input("Alertar si cambia más de %", 1, 100, 30)

if not up:
    st.stop()

raw = read_excel(up)
if "sku" not in raw and "item_id" not in raw:
    st.error("El Excel necesita una columna 'sku' (o 'item_id').")
    st.stop()
if "precio" not in raw:
    st.error("El Excel necesita una columna 'precio'.")
    st.stop()
keycol = "sku" if "sku" in raw else "item_id"

index = catalog_index(client)
m = match(index, raw[keycol], prefix=prefix)
raw["_k"] = raw[keycol].astype(str).str.strip()
m["_k"] = m["clave"].astype(str).str.strip()
df = m.merge(raw[["_k", "precio"]].drop_duplicates("_k"), on="_k", how="left")


def check(r):
    if not r.get("item_id"):
        return pd.Series({"precio_nuevo": None, "var_%": None, "valido": False, "obs": "SKU/ID no encontrado"})
    new = to_number(r.get("precio"))
    if not new or new <= 0:
        return pd.Series({"precio_nuevo": None, "var_%": None, "valido": False, "obs": "Precio inválido"})
    new = round(new) if round_int else round(new, 2)
    cur = to_number(r.get("precio_original")) or to_number(r.get("precio_actual"))
    var = round((new / cur - 1) * 100, 1) if cur else None
    obs, ok = "", True
    if cur and new == cur:
        obs, ok = "Sin cambio", False
    elif var is not None and abs(var) > alert:
        obs = f"⚠️ Cambio de {var}%"
    if r.get("precio_original") and not pd.isna(r.get("precio_original")):
        obs = (obs + " · " if obs else "") + "Tiene promo activa: MeLi puede rechazar o bajar la promo"
    return pd.Series({"precio_nuevo": new, "var_%": var, "valido": ok, "obs": obs})


df = pd.concat([df, df.apply(check, axis=1)], axis=1)
dups = df["item_id"].notna() & df.duplicated("item_id")
df.loc[dups, ["valido", "obs"]] = [False, "Item repetido (otra fila ya lo actualiza)"]

show = [c for c in ["clave", "item_id", "titulo", "estado", "variaciones", "precio_actual", "precio_original",
                    "precio_nuevo", "var_%", "valido", "obs"] if c in df]
v1, v2, v3 = st.columns(3)
v1.metric("Filas Excel", len(raw))
v2.metric("Publicaciones a actualizar", int(df["valido"].sum()))
v3.metric("Con problemas / sin cambio", int((~df["valido"]).sum()))
ed = st.data_editor(df[show], width="stretch", hide_index=True, key="prev_precios",
                    disabled=[c for c in show if c != "valido"])

todo = df[ed["valido"].values].to_dict("records")
if not todo:
    st.stop()

ok = st.checkbox(f"Confirmo actualizar el precio de {len(todo)} publicaciones")
if st.button(f"🚀 Actualizar {len(todo)} precios", type="primary", disabled=not ok):
    res = run_bulk(todo, lambda r: update_price(client, r["item_id"], r["precio_nuevo"], r.get("variation_ids")),
                   label="Actualizando precios")
    keep = [c for c in ["clave", "item_id", "titulo", "precio_actual", "precio_nuevo", "var_%", "resultado", "error",
                        "procesado"] if c in res]
    show_results(res[keep], f"resultado_precios_{datetime.now():%Y%m%d_%H%M}.xlsx")
    st.cache_data.clear()  # fuerza releer catálogo con precios nuevos
