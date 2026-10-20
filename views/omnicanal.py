from datetime import datetime

import pandas as pd
import streamlit as st

from meli import omni
from meli import shopify as sh
from meli.api import MeliClient
from meli.auth import get_token_manager
from meli.carga import REDONDEOS, mode_picker
from meli.excel import to_number, to_xlsx
from meli.theme import hero
from meli.ui import catalog_index, pick_account

st.session_state["_page"] = "omni"
hero("Precios omnicanal", "Un solo lugar para el precio de cada modelo-color en MercadoLibre y en tu tienda Shopify: "
     "compará, igualá y aplicá en uno o en ambos canales.", "PRECIOS · MELI + SHOPIFY")

stores = sh.stores()
if not stores:
    st.warning("No hay tiendas Shopify configuradas. Agregalas en Secrets (ver README → Shopify) y reiniciá la app.")
    st.stop()

client = pick_account()
tm = get_token_manager()
alias = tm.accounts().get(client.user_id, {}).get("alias")
tiendas = st.sidebar.multiselect("Tiendas Shopify", list(stores), default=sh.stores_for_meli(alias),
                                 format_func=lambda k: stores[k]["nombre"], key=f"omni_st_{client.user_id}")
if not tiendas:
    st.info("Elegí al menos una tienda Shopify en la barra lateral.")
    st.stop()

mode = mode_picker("omni")
c1, c2 = st.columns([3, 1])
if c2.button("🔄 Refrescar Shopify", key="omni_ref_sh"):
    sh.variants_for(tiendas, refresh=True)
index = catalog_index(client)
with st.spinner("Leyendo catálogo Shopify…"):
    variants = sh.variants_for(tiendas)
c1.caption(f"Shopify: {variants['product_id'].nunique() if not variants.empty else 0} productos · "
           f"{variants['sku'].notna().sum() if not variants.empty else 0} SKUs en {', '.join(stores[t]['nombre'] for t in tiendas)}")

# ---------------------------------------------------------------- tabla de carga
ss = st.session_state
SK, VK, LK = "omni_grid", "omni_v", "omni_look"
ss.setdefault(VK, 0)
COLS = ["clave", "meli_actual", "shop_actual", "dif_%", "meli_nuevo", "shop_nuevo", "meli_publ", "shop_var", "estado"]


def empty(n=12):
    d = pd.DataFrame({c: pd.Series([None] * n, dtype="float") for c in COLS})
    d["clave"] = pd.Series([None] * n, dtype="string")
    d["estado"] = pd.Series([None] * n, dtype="string")
    return d[COLS]


def store(df):
    ss[SK] = df.reset_index(drop=True)
    ss[VK] += 1
    st.rerun()


ss.setdefault(SK, empty())
with st.expander("📋 Pegar lista o subir Excel", expanded=ss[SK]["clave"].dropna().empty):
    st.caption("Columna 1: modelo-color / SKU. Opcional: columna 2 = precio nuevo (se usa para ambos canales).")
    a, b = st.columns(2)
    txt = a.text_area("Pegar", height=140, key="omni_paste", label_visibility="collapsed",
                      placeholder="K1342233W-KSA02\t104999\nCL1234-010")
    up = b.file_uploader("Excel", type=["xlsx", "csv"], key="omni_up", label_visibility="collapsed")
    if b.button("⬇️ Cargar en la tabla", type="primary", key="omni_load"):
        rows = []
        if up is not None:
            from meli.excel import read_excel
            x = read_excel(up)
            if "clave" in x:
                val = next((c for c in ("precio", "precio_promo") if c in x), None)
                rows += [{"clave": str(r["clave"]).strip(), "p": to_number(r.get(val)) if val else None}
                         for _, r in x.iterrows()]
        for line in (txt or "").splitlines():
            parts = [p.strip() for p in (line.split("\t") if "\t" in line else line.split(";"))]
            if parts and parts[0]:
                rows.append({"clave": parts[0], "p": to_number(parts[1]) if len(parts) > 1 else None})
        rows = [r for r in rows if r["clave"] and r["clave"].lower() not in {"nan", "modelo_color", "sku"}]
        if rows:
            new = pd.DataFrame(rows).drop_duplicates("clave", keep="last")
            df = empty(0)
            df = pd.concat([df, pd.DataFrame({"clave": new["clave"]})], ignore_index=True)
            df["meli_nuevo"] = new["p"].values
            df["shop_nuevo"] = new["p"].values
            ss.pop(LK, None)
            store(df)

cfg = {
    "clave": st.column_config.TextColumn("Modelo-color / SKU", width="medium"),
    "meli_actual": st.column_config.NumberColumn("MeLi actual", format="localized", disabled=True),
    "shop_actual": st.column_config.NumberColumn("Shopify actual", format="localized", disabled=True),
    "dif_%": st.column_config.NumberColumn("MeLi vs Shop %", format="%.1f%%", disabled=True,
                                           help="Positivo = MeLi más caro que Shopify"),
    "meli_nuevo": st.column_config.NumberColumn("MeLi nuevo", format="localized", min_value=0),
    "shop_nuevo": st.column_config.NumberColumn("Shopify nuevo", format="localized", min_value=0),
    "meli_publ": st.column_config.NumberColumn("Publ. MeLi", disabled=True, width="small"),
    "shop_var": st.column_config.NumberColumn("Var. Shop", disabled=True, width="small"),
    "estado": st.column_config.TextColumn("Estado", disabled=True, width="large"),
}
ed = st.data_editor(ss[SK][COLS], num_rows="dynamic", hide_index=True, width="stretch", column_config=cfg,
                    key=f"omni_ed_{ss[VK]}").copy()
ed["clave"] = ed["clave"].astype("string").str.strip()
claves = [c for c in ed["clave"].dropna().tolist() if c]
sig = (tuple(claves), mode, len(index), len(variants))
if claves and ss.get(LK) != sig:
    with st.spinner("Buscando precios en MeLi y Shopify…"):
        info = omni.lookup(index, variants, claves, mode).drop_duplicates("clave")
    base = ed[ed["clave"].fillna("") != ""][["clave", "meli_nuevo", "shop_nuevo"]].drop_duplicates("clave", keep="last")
    ss[LK] = sig
    store(base.merge(info, on="clave", how="left")[COLS])

# ---------------------------------------------------------------- reglas masivas
st.markdown("**Reglas rápidas**")
r1, r2, r3, r4 = st.columns([1.3, 1, 1.4, 1])
regla = r1.selectbox("Regla", ["pct", "meli_a_shop", "shop_a_meli", "copiar"], key="omni_regla", format_func={
    "pct": "Aplicar % sobre el actual", "meli_a_shop": "Shopify = precio MeLi (± %)",
    "shop_a_meli": "MeLi = precio Shopify (± %)", "copiar": "Shopify nuevo = MeLi nuevo"}.get)
pct = r2.number_input("%", value=0.0 if regla != "pct" else 10.0, step=5.0, key=f"omni_pct_{regla}")
how = r3.selectbox("Redondeo", list(REDONDEOS), format_func=REDONDEOS.get, key="omni_rnd")
canal_regla = st.radio("Aplicar la regla a", ["Ambos", "Solo MeLi", "Solo Shopify"], horizontal=True,
                       key="omni_canal_regla") if regla == "pct" else None
if r4.button("Aplicar regla", width="stretch", key="omni_ap"):
    df = ed[ed["clave"].fillna("") != ""].copy()
    f = 1 + pct / 100
    if regla == "pct":
        if canal_regla in ("Ambos", "Solo MeLi"):
            df["meli_nuevo"] = df["meli_actual"].map(lambda v: omni.regla_precio(v, f, how))
        if canal_regla in ("Ambos", "Solo Shopify"):
            df["shop_nuevo"] = df["shop_actual"].map(lambda v: omni.regla_precio(v, f, how))
    elif regla == "meli_a_shop":
        df["shop_nuevo"] = df["meli_actual"].map(lambda v: omni.regla_precio(v, f, how))
    elif regla == "shop_a_meli":
        df["meli_nuevo"] = df["shop_actual"].map(lambda v: omni.regla_precio(v, f, how))
    else:
        df["shop_nuevo"] = df["meli_nuevo"]
    store(df[COLS])
b1, b2, _ = st.columns([1, 1, 3])
if b1.button("🔄 Volver a buscar", key="omni_rl"):
    ss.pop(LK, None)
    store(ed[ed["clave"].fillna("") != ""][COLS])
if b2.button("🗑️ Limpiar", key="omni_clr"):
    ss.pop(LK, None)
    store(empty())

data = ed[ed["clave"].fillna("") != ""]
if data.empty or (data["meli_nuevo"].isna().all() and data["shop_nuevo"].isna().all()):
    st.info("Cargá modelos-color y completá **MeLi nuevo** y/o **Shopify nuevo** (a mano o con una regla).")
    st.stop()

# ---------------------------------------------------------------- canales y vista previa
st.divider()
st.subheader("Vista previa por canal")
k1, k2, k3 = st.columns([1, 1, 2])
en_meli = k1.checkbox("Aplicar en MeLi", value=True, key="omni_c_meli")
en_shop = k2.checkbox("Aplicar en Shopify", value=True, key="omni_c_shop")
tachado = k3.selectbox("Precio tachado en Shopify", list(omni.TACHADO), format_func=omni.TACHADO.get, key="omni_tach")

pm = omni.plan_meli(index, {r["clave"]: r["meli_nuevo"] for _, r in data.iterrows() if pd.notna(r["meli_nuevo"])},
                    mode) if en_meli else pd.DataFrame()
ps = omni.plan_shop(variants, {r["clave"]: r["shop_nuevo"] for _, r in data.iterrows() if pd.notna(r["shop_nuevo"])},
                    mode, tachado) if en_shop else pd.DataFrame()

m = st.columns(4)
m[0].metric("Publicaciones MeLi a cambiar", len(pm))
m[1].metric("Variantes Shopify a cambiar", len(ps))
m[2].metric("Productos Shopify", ps["product_id"].nunique() if not ps.empty else 0)
m[3].metric("Modelos-color", data["clave"].nunique())

t1, t2 = st.tabs([f"MeLi ({len(pm)})", f"Shopify ({len(ps)})"])
with t1:
    if pm.empty:
        st.caption("Sin cambios en MeLi.")
    else:
        pv = pm[["clave", "titulo", "item_id", "precio_lista", "precio_nuevo"]].copy()
        pv["var_%"] = ((pv["precio_nuevo"] / pv["precio_lista"] - 1) * 100).round(1)
        st.dataframe(pv, hide_index=True, width="stretch")
        if pm["precio_original"].notna().any():
            st.warning(f"{int(pm['precio_original'].notna().sum())} publicaciones tienen promo activa en MeLi.")
with t2:
    if ps.empty:
        st.caption("Sin cambios en Shopify.")
    else:
        pv = ps[["clave", "tienda_nombre", "producto", "sku", "precio", "precio_nuevo", "precio_tachado",
                 "tachado_nuevo"]].copy()
        pv["var_%"] = ((pv["precio_nuevo"] / pv["precio"] - 1) * 100).round(1)
        st.dataframe(pv, hide_index=True, width="stretch")
        bad = ps[ps["tachado_nuevo"].notna() & (ps["tachado_nuevo"] <= ps["precio_nuevo"])]
        if not bad.empty:
            st.warning(f"{len(bad)} variantes quedarían con precio tachado menor o igual al precio: no se va a ver "
                       "como descuento. Elegí *Quitar el precio tachado* si corresponde.")

if pm.empty and ps.empty:
    st.info("No hay cambios para aplicar.")
    st.stop()

st.divider()
ok = st.checkbox(f"Confirmo aplicar {len(pm)} cambios en MeLi y {len(ps)} en Shopify", key="omni_ok")
if st.button("🚀 Aplicar en los canales elegidos", type="primary", disabled=not ok):
    res = omni.aplicar(pm, ps, {client.user_id: client}, client.user_id, tachado)
    ss["omni_res"] = res
    st.cache_data.clear()

res = ss.get("omni_res")
if res is not None and not res.empty:
    ok_n, err_n = (res["resultado"] == "OK").sum(), (res["resultado"] == "ERROR").sum()
    (st.success if not err_n else st.warning)(f"Listo: {ok_n} OK · {err_n} con error")
    st.dataframe(res, hide_index=True, width="stretch")
    st.download_button("⬇️ Resultado Excel", to_xlsx(res), file_name=f"omnicanal_{datetime.now():%Y%m%d_%H%M}.xlsx")
