from datetime import datetime

import pandas as pd
import streamlit as st

from meli import inconsistencias as inc
from meli.api import MeliClient
from meli.auth import get_token_manager
from meli.bulk import run_bulk
from meli.excel import to_xlsx
from meli.prices import update_price
from meli.ui import catalog_index, index_for, pick_account, show_results

st.session_state["_page"] = "inconsistencias"
st.title("⚖️ Precios distintos")
st.caption("Busca en tus publicaciones el mismo artículo con precios diferentes (por ejemplo, talles de una misma "
           "calza a distinto precio) y te deja igualarlos en bloque o publicación por publicación. "
           "Compara siempre el **precio de lista** (sin promo).")
client = pick_account()
tm = get_token_manager()
accounts = tm.accounts()

alcance = st.radio("Analizar", ["Cuenta seleccionada", "Todas las cuentas"], horizontal=True, key="inc_scope")
index = catalog_index(client)
if alcance == "Todas las cuentas":
    partes = []
    prog = st.progress(0.0, text="Leyendo catálogos…")
    for n, (uid, a) in enumerate(accounts.items(), 1):
        it = inc.items_table(index if uid == client.user_id else index_for(uid))
        it["cuenta"], it["uid"] = a.get("alias") or a.get("nickname") or uid, uid
        partes.append(it)
        prog.progress(n / len(accounts), text=f"Leyendo catálogos… {a.get('alias')}")
    prog.empty()
    items = pd.concat(partes, ignore_index=True)
else:
    items = inc.items_table(index)
    items["uid"] = client.user_id

con_familia = items["familia"].notna().mean() if len(items) else 0
st.caption(f"{len(items['item_id'].unique())} publicaciones analizadas · "
           f"{con_familia:.0%} con datos de publicación agrupada (formato nuevo de MeLi). "
           "El resto se agrupa por modelo-color del SKU.")

# ---------------------------------------------------------------- filtros
c1, c2 = st.columns([2, 1])
how = c1.radio("Qué considerar el mismo artículo", list(inc.AGRUPAR), format_func=inc.AGRUPAR.get, key="inc_how",
               help="Las publicaciones nuevas de MeLi tienen una publicación por talle agrupadas en una misma ficha. "
                    "'Modelo-color por SKU' agrupa por el SKU sin el último segmento (el talle), "
                    "útil también para publicaciones duplicadas del mismo artículo.")
estados = c2.multiselect("Estados", ["active", "paused"], ["active", "paused"], key="inc_est")
c1, c2 = st.columns([2, 1])
texto = c1.text_input("Buscar (título, SKU o modelo)", key="inc_txt", placeholder="Ej: calza, K238187ZW")
min_diff = c2.number_input("Diferencia mínima %", 0.0, 500.0, 1.0, step=1.0, key="inc_dif")

summ, det = inc.find_groups(items, how, min_diff, texto, tuple(estados))

m = st.columns(4)
m[0].metric("Artículos con precios distintos", len(summ))
m[1].metric("Publicaciones involucradas", det["item_id"].nunique() if not det.empty else 0)
m[2].metric("Mayor diferencia", f"{summ['dif_%'].max():.0f}%" if not summ.empty else "—")
m[3].metric("Con promo activa", int(summ["en_promo"].sum()) if not summ.empty else 0)

if summ.empty:
    st.success("No hay artículos con precios distintos con estos filtros. 🎉")
    st.stop()

# ---------------------------------------------------------------- regla masiva
st.subheader("1 · Elegí el precio para cada artículo")
regla = st.radio("Regla para todos", list(inc.REGLAS), format_func=inc.REGLAS.get, horizontal=True, key="inc_regla")
summ = summ.copy()
summ["precios"] = summ["grupo"].map(inc.precios_texto(det))
summ["precio_objetivo"] = inc.objetivo(summ, regla).values
summ.insert(0, "igualar", True)
cols = ["igualar"] + (["cuenta"] if "cuenta" in summ else []) + ["titulo", "publicaciones", "precios", "min", "max", "dif_%", "precio_objetivo", "en_promo", "grupo"]
ed = st.data_editor(
    summ[cols], hide_index=True, width="stretch", key=f"inc_sum_{how}_{regla}_{texto}_{min_diff}",
    disabled=[c for c in cols if c not in ("igualar", "precio_objetivo")],
    column_config={
        "igualar": st.column_config.CheckboxColumn("Igualar", width="small"),
        "precios": st.column_config.TextColumn("Precios actuales", width="medium"),
        "min": st.column_config.NumberColumn("Mín.", format="localized"),
        "max": st.column_config.NumberColumn("Máx.", format="localized"),
        "precio_objetivo": st.column_config.NumberColumn("Precio a aplicar", format="localized", min_value=0),
        "en_promo": st.column_config.NumberColumn("En promo", width="small"),
        "grupo": st.column_config.TextColumn("Grupo", width="small"),
    },
)
st.caption("Podés cambiar el **Precio a aplicar** de cada artículo o destildar *Igualar* en los que no quieras tocar.")
st.download_button("⬇️ Excel de artículos con precios distintos",
                   to_xlsx(det.drop(columns=["variation_ids"], errors="ignore")),
                   file_name=f"precios_distintos_{datetime.now():%Y%m%d_%H%M}.xlsx")

# ---------------------------------------------------------------- detalle publicación por publicación
sel = ed[ed["igualar"]]
obj = dict(zip(sel["grupo"], sel["precio_objetivo"]))
d = det[det["grupo"].isin(obj)].copy()
d["precio_nuevo"] = d["grupo"].map(obj)
d["aplicar"] = d["precio_nuevo"].notna() & (d["precio_nuevo"] != d["precio_lista"])

st.subheader("2 · Revisá publicación por publicación")
st.caption("Por defecto se tildan solo las que cambian de precio. Podés editar el precio de una publicación puntual.")
dcols = ["aplicar"] + (["cuenta"] if "cuenta" in d else []) + ["titulo", "color", "skus", "item_id", "estado", "stock", "precio_lista", "precio_venta",
         "precio_nuevo", "en_promo", "permalink"]
sig = hash(tuple(sorted((k, float(v) if pd.notna(v) else -1) for k, v in obj.items())))
ed2 = st.data_editor(
    d[dcols].sort_values(["titulo", "color", "precio_lista"]), hide_index=True, width="stretch",
    key=f"inc_det_{sig}_{how}",
    disabled=[c for c in dcols if c not in ("aplicar", "precio_nuevo")],
    column_config={
        "aplicar": st.column_config.CheckboxColumn("Aplicar", width="small"),
        "precio_lista": st.column_config.NumberColumn("Precio actual", format="localized"),
        "precio_venta": st.column_config.NumberColumn("Precio venta (c/promo)", format="localized"),
        "precio_nuevo": st.column_config.NumberColumn("Precio nuevo", format="localized", min_value=0),
        "permalink": st.column_config.LinkColumn("Link", display_text="ver"),
    },
)

todo = ed2[ed2["aplicar"] & ed2["precio_nuevo"].notna() & (ed2["precio_nuevo"] > 0)]
todo = todo[todo["precio_nuevo"] != todo["precio_lista"]].drop_duplicates("item_id")
todo = todo.merge(d[["item_id", "variation_ids", "uid"]].drop_duplicates("item_id"), on="item_id", how="left")
if todo.empty:
    st.info("No hay publicaciones para cambiar.")
    st.stop()

promo = int(todo["en_promo"].sum())
if promo:
    st.warning(f"{promo} publicaciones tienen promo activa: MeLi puede rechazar el cambio o recalcular la promo.")
sube = int((todo["precio_nuevo"] > todo["precio_lista"]).sum())
baja = int((todo["precio_nuevo"] < todo["precio_lista"]).sum())
st.divider()
ok = st.checkbox(f"Confirmo cambiar el precio de {len(todo)} publicaciones ({sube} suben · {baja} bajan)")
if st.button(f"🚀 Igualar {len(todo)} publicaciones", type="primary", disabled=not ok):
    clients = {uid: MeliClient(tm, uid) for uid in todo["uid"].dropna().unique()}
    res = run_bulk(todo.to_dict("records"),
                   lambda r: update_price(clients.get(r.get("uid"), client), r["item_id"], r["precio_nuevo"],
                                          r.get("variation_ids")),
                   label="Igualando precios")
    keep = [c for c in ["cuenta", "titulo", "color", "skus", "item_id", "precio_lista", "precio_nuevo", "resultado", "error",
                        "procesado"] if c in res]
    show_results(res[keep], f"resultado_igualar_{datetime.now():%Y%m%d_%H%M}.xlsx")
    st.cache_data.clear()
