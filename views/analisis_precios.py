from datetime import datetime

import pandas as pd
import streamlit as st

from meli import omni
from meli import shopify as sh
from meli.api import MeliClient
from meli.auth import get_token_manager
from meli.carga import REDONDEOS
from meli.excel import to_xlsx
from meli.theme import hero
from meli.ui import catalog_index, index_for, pick_account

st.session_state["_page"] = "analisis"
hero("Análisis de precios", "Todo el catálogo cruzado entre MercadoLibre y Shopify: brechas de precio, cobertura de "
     "canales, stock y promos, con ajuste masivo en un clic.", "PRECIOS · INTELIGENCIA")

stores = sh.stores()
if not stores:
    st.warning("No hay tiendas Shopify configuradas. Agregalas en Secrets (ver README → Shopify) y reiniciá la app.")
    st.stop()

client = pick_account()
tm = get_token_manager()
accounts = tm.accounts()

c1, c2, c3 = st.columns([1.2, 1.4, 1])
alcance = c1.radio("Cuentas MeLi", ["Seleccionada", "Todas"], horizontal=True, key="an_scope")
alias = accounts.get(client.user_id, {}).get("alias")
tiendas = c2.multiselect("Tiendas Shopify", list(stores),
                         default=list(stores) if alcance == "Todas" else sh.stores_for_meli(alias),
                         format_func=lambda k: stores[k]["nombre"], key=f"an_st_{alcance}_{client.user_id}")
nivel = c3.radio("Comparar por", ["modelo", "sku"], horizontal=True, key="an_nivel",
                 format_func={"modelo": "Modelo-color", "sku": "SKU (talle)"}.get)

index = catalog_index(client)
if alcance == "Todas":
    partes = []
    for uid, a in accounts.items():
        ix = (index if uid == client.user_id else index_for(uid)).copy()
        ix["cuenta"], ix["uid"] = a.get("alias") or uid, uid
        partes.append(ix)
    mindex = pd.concat(partes, ignore_index=True)
else:
    mindex = index.copy()
    mindex["cuenta"], mindex["uid"] = alias or client.user_id, client.user_id
with st.spinner("Leyendo Shopify…"):
    variants = sh.variants_for(tiendas)

df = omni.analisis(mindex, variants, nivel)
ambos = df[df["situacion"].isin(["Igual", "MeLi más caro", "MeLi más barato"])]

m = st.columns(6)
m[0].metric("Artículos", len(df))
m[1].metric("En ambos canales", len(ambos))
m[2].metric("Solo MeLi", int((df["situacion"] == "Solo MeLi").sum()))
m[3].metric("Solo Shopify", int((df["situacion"] == "Solo Shopify").sum()))
m[4].metric("MeLi más caro", int((df["situacion"] == "MeLi más caro").sum()))
m[5].metric("Brecha media", f"{ambos['dif_%'].abs().mean():.1f}%" if not ambos.empty else "—")

# ---------------------------------------------------------------- filtros
f1, f2, f3 = st.columns([2, 1, 1.4])
sits = f1.multiselect("Situación", ["MeLi más caro", "MeLi más barato", "Igual", "Solo MeLi", "Solo Shopify"],
                      default=["MeLi más caro", "MeLi más barato"], key="an_sit")
umbral = f2.number_input("Brecha mínima % (absoluta)", 0.0, 500.0, 1.0, step=0.5, key="an_um")
q = f3.text_input("Buscar", key="an_q", placeholder="título, modelo-color…")
view = df[df["situacion"].isin(sits)]
view = view[view["dif_%"].isna() | (view["dif_%"].abs() >= umbral)]
if q:
    ql = q.lower()
    view = view[view["nombre"].fillna("").str.lower().str.contains(ql, regex=False)
                | view["clave"].fillna("").str.lower().str.contains(ql, regex=False)]
view = view.sort_values("dif_%", key=lambda s: s.abs(), ascending=False, na_position="last")

st.caption(f"{len(view)} artículos con estos filtros. Tildá **Ajustar** en los que quieras corregir.")
view = view.copy()
view.insert(0, "ajustar", False)
cols = ["ajustar", "situacion", "nombre", "clave", "cuenta", "tienda", "meli_precio", "shop_precio", "dif_%",
        "shop_tachado", "meli_promo", "meli_stock", "shop_stock", "meli_publ", "shop_var", "meli_link", "shop_link"]
cols = [c for c in cols if c in view]
sel_all = st.checkbox("Tildar todos los filtrados", key="an_all")
if sel_all:
    view["ajustar"] = True
ed = st.data_editor(
    view[cols], hide_index=True, width="stretch", key=f"an_ed_{nivel}_{len(view)}_{sel_all}",
    disabled=[c for c in cols if c != "ajustar"],
    column_config={
        "meli_precio": st.column_config.NumberColumn("MeLi", format="localized"),
        "shop_precio": st.column_config.NumberColumn("Shopify", format="localized"),
        "shop_tachado": st.column_config.NumberColumn("Tachado Shop", format="localized"),
        "dif_%": st.column_config.NumberColumn("MeLi vs Shop", format="%.1f%%"),
        "meli_link": st.column_config.LinkColumn("MeLi", display_text="ver"),
        "shop_link": st.column_config.LinkColumn("Shop", display_text="ver"),
        "meli_promo": st.column_config.CheckboxColumn("Promo MeLi"),
    },
)
st.download_button("⬇️ Excel del análisis (todo)", to_xlsx(df), file_name=f"analisis_precios_{datetime.now():%Y%m%d_%H%M}.xlsx")

sel = view[ed["ajustar"].values]
sel = sel[sel["meli_precio"].notna() & sel["shop_precio"].notna()]
if sel.empty:
    st.stop()

# ---------------------------------------------------------------- ajuste
st.divider()
st.subheader(f"Ajustar {len(sel)} artículos")
a1, a2, a3, a4 = st.columns([1.6, 0.8, 1.2, 1.4])
regla = a1.selectbox("Regla", ["shop_a_meli", "meli_a_shop"], key="an_regla", format_func={
    "shop_a_meli": "Shopify = precio MeLi (± %)", "meli_a_shop": "MeLi = precio Shopify (± %)"}.get)
pct = a2.number_input("%", value=0.0, step=1.0, key="an_pct",
                      help="Ej: -5 = el canal destino queda 5% más barato que el de referencia.")
how = a3.selectbox("Redondeo", list(REDONDEOS), format_func=REDONDEOS.get, key="an_rnd")
tachado = a4.selectbox("Tachado Shopify", list(omni.TACHADO), format_func=omni.TACHADO.get, key="an_tach")
f = 1 + pct / 100
if regla == "shop_a_meli":
    objetivo = {r["clave"]: omni.regla_precio(r["meli_precio"], f, how) for _, r in sel.iterrows()}
    ps = omni.plan_shop(variants, objetivo, "modelo" if nivel == "modelo" else "exacto|no", tachado)
    pm = pd.DataFrame()
else:
    objetivo = {r["clave"]: omni.regla_precio(r["shop_precio"], f, how) for _, r in sel.iterrows()}
    pm = omni.plan_meli(mindex, objetivo, "modelo" if nivel == "modelo" else "exacto|no")
    if not pm.empty and "uid" not in pm:
        pm = pm.merge(mindex[["item_id", "uid"]].drop_duplicates("item_id"), on="item_id", how="left")
    ps = pd.DataFrame()

n = len(pm) + len(ps)
st.write(f"Se van a cambiar **{len(pm)} publicaciones MeLi** y **{len(ps)} variantes Shopify**.")
prev = (pm[["clave", "titulo", "item_id", "precio_lista", "precio_nuevo"]].rename(columns={"precio_lista": "actual"})
        if not pm.empty else
        ps[["clave", "producto", "sku", "precio", "precio_nuevo"]].rename(columns={"precio": "actual"}) if not ps.empty
        else pd.DataFrame())
if not prev.empty:
    st.dataframe(prev, hide_index=True, width="stretch")
ok = st.checkbox(f"Confirmo aplicar {n} cambios", key="an_ok", disabled=n == 0)
if st.button("🚀 Aplicar ajuste", type="primary", disabled=not ok or n == 0):
    clients = {uid: MeliClient(tm, uid) for uid in (pm["uid"].dropna().unique() if not pm.empty and "uid" in pm else [])}
    clients.setdefault(client.user_id, client)
    res = omni.aplicar(pm, ps, clients, client.user_id, tachado)
    st.session_state["an_res"] = res
    st.cache_data.clear()

res = st.session_state.get("an_res")
if res is not None and not res.empty:
    ok_n, err_n = (res["resultado"] == "OK").sum(), (res["resultado"] == "ERROR").sum()
    (st.success if not err_n else st.warning)(f"Listo: {ok_n} OK · {err_n} con error")
    st.dataframe(res, hide_index=True, width="stretch")
    st.download_button("⬇️ Resultado Excel", to_xlsx(res), file_name=f"ajuste_{datetime.now():%Y%m%d_%H%M}.xlsx")
