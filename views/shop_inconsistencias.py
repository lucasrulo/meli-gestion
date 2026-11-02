"""Precios distintos en Shopify: mismo SKU / modelo-color / producto con variantes a distinto precio → igualar."""
from datetime import datetime

import pandas as pd
import streamlit as st

from meli import shop_ops as ops
from meli.excel import to_xlsx
from meli.inconsistencias import REGLAS, strip_size
from meli.selector_marca import corto
from meli.shop_bulk import catalogo
from meli.shop_ui import ESTADOS, pick_store, progreso
from meli.shopify import ShopifyError, stores
from meli.theme import hero

hero("Precios distintos Shopify", "Detecta el mismo artículo con variantes a precios diferentes y las iguala en bloque.",
     "SHOPIFY · AUDITORÍA")

AGRUPAR = {
    "modelo_color": "Modelo-color por SKU (todos los talles del mismo color, aunque estén en productos distintos)",
    "sku": "Mismo SKU exacto (repetido en varias variantes o productos)",
    "producto": "Producto completo (todas sus variantes)",
}
CAMPOS = {"precio": "Precio de venta", "precio_tachado": "Precio tachado"}

alcance = st.radio("Analizar", ["Tienda seleccionada", "Todas las tiendas"], horizontal=True, key="sinc_scope")
todas = stores()
if alcance == "Tienda seleccionada":
    claves = [pick_store()]
else:
    claves = list(todas)

partes = []
bar = st.progress(0.0, text="Leyendo catálogos…") if len(claves) > 1 else None
for n, k in enumerate(claves, 1):
    try:
        with st.spinner(f"Leyendo catálogo de {corto(todas[k]['nombre'])}…"):
            P, V, _, _ = catalogo(k)
    except ShopifyError as e:
        st.warning(f"{todas[k]['nombre']}: {e}")
        continue
    if bar:
        bar.progress(n / len(claves), text=f"Leyendo catálogos… {corto(todas[k]['nombre'])}")
    info = P.set_index("product_id")
    v = V[V["product_id"].isin(info.index)].copy()
    v["tienda"], v["marca"] = k, corto(todas[k]["nombre"])
    v["titulo"] = v["product_id"].map(info["titulo"])
    v["estado"] = v["product_id"].map(info["estado"])
    v["url"] = v["product_id"].map(info["url"]).fillna("")
    v["foto"] = v["product_id"].map(info["foto"]).fillna("")
    partes.append(v)
if bar:
    bar.empty()
if not partes:
    st.info("No pude leer ningún catálogo.")
    st.stop()
items = pd.concat(partes, ignore_index=True)
items["sku"] = items["sku"].fillna("").astype(str).str.strip()
items["modelo_color"] = items["sku"].map(lambda s: strip_size(s) if s else None)
items["talle"] = items["variante"].fillna("").astype(str).map(lambda x: x.split("/")[-1].strip())

# ---------------------------------------------------------------- filtros
c1, c2 = st.columns([2, 1])
how = c1.radio("Qué considerar el mismo artículo", list(AGRUPAR), format_func=AGRUPAR.get, key="sinc_how")
estados = c2.multiselect("Estados", list(ESTADOS), ["ACTIVE", "UNLISTED", "DRAFT"], format_func=ESTADOS.get, key="sinc_est")
c1, c2, c3 = st.columns([2, 1, 1])
texto = c1.text_input("Buscar (título, SKU o modelo-color)", key="sinc_txt", placeholder="Ej: club c, K238187ZW")
min_diff = c2.number_input("Diferencia mínima %", 0.0, 500.0, 0.0, step=0.5, key="sinc_dif")
solo_stock = c3.toggle("Solo variantes con stock", value=False, key="sinc_stock")
campo = st.radio("Comparar", list(CAMPOS), format_func=CAMPOS.get, horizontal=True, key="sinc_campo",
                 help="Precio tachado: detecta talles donde uno muestra «antes $X» distinto a otro.")

base = items[items["estado"].isin(estados)] if estados else items
if solo_stock:
    base = base[base["stock"].fillna(0) > 0]
key_col = {"modelo_color": "modelo_color", "sku": "sku", "producto": "product_id"}[how]
base = base.copy()
base["grupo"] = base["tienda"] + "|" + base[key_col].fillna("").astype(str)
base = base[base[key_col].fillna("").astype(str) != ""]
if how == "sku":
    base = base[base["sku"] != ""]
base["precio_cmp"] = base[campo]
cmp = base[base["precio_cmp"].notna()]

g = cmp.groupby("grupo")["precio_cmp"]
summ = pd.DataFrame({"min": g.min(), "max": g.max(), "variantes": g.size(),
                     "moda": g.agg(lambda s: s.mode().max() if len(s.mode()) else s.max())})
summ = summ[summ["max"] > summ["min"]]
summ["dif_%"] = ((summ["max"] / summ["min"] - 1) * 100).round(1)
summ = summ[summ["dif_%"] >= min_diff].reset_index()
primeros = cmp.drop_duplicates("grupo").set_index("grupo")
summ["marca"] = summ["grupo"].map(primeros["marca"])
summ["titulo"] = summ["grupo"].map(primeros["titulo"])
summ["modelo_color"] = summ["grupo"].map(lambda x: x.split("|", 1)[1]) if how != "producto" else \
    summ["grupo"].map(primeros["modelo_color"])
summ["productos"] = summ["grupo"].map(cmp.groupby("grupo")["product_id"].nunique())
summ["foto"] = summ["grupo"].map(primeros["foto"])
if texto:
    t = texto.strip().lower()
    hit = cmp[cmp["titulo"].str.lower().str.contains(t, regex=False, na=False)
              | cmp["sku"].str.lower().str.contains(t, regex=False, na=False)]["grupo"]
    summ = summ[summ["grupo"].isin(set(hit))]
det = cmp[cmp["grupo"].isin(summ["grupo"])].copy()

with st.expander("🔎 ¿No aparece un artículo? Diagnóstico"):
    qd = st.text_input("Título o SKU", key="sinc_diag", placeholder="Ej: club c 85")
    if qd:
        q = qd.strip().lower()
        dg = items[items["titulo"].str.lower().str.contains(q, regex=False, na=False)
                   | items["sku"].str.lower().str.contains(q, regex=False, na=False)]
        st.caption(f"{len(dg)} variantes. Si tienen el **mismo precio** o quedan en **grupos distintos** "
                   "(otro modelo-color / estado filtrado), no aparecen arriba.")
        st.dataframe(dg[["marca", "titulo", "estado", "sku", "modelo_color", "talle", "stock", "precio", "precio_tachado"]],
                     hide_index=True, width="stretch",
                     column_config={"precio": st.column_config.NumberColumn("Precio", format="localized"),
                                    "precio_tachado": st.column_config.NumberColumn("Tachado", format="localized")})

m = st.columns(4)
m[0].metric("Artículos con precios distintos", len(summ))
m[1].metric("Variantes involucradas", len(det))
m[2].metric("Productos involucrados", det["product_id"].nunique() if not det.empty else 0)
m[3].metric("Mayor diferencia", f"{summ['dif_%'].max():.0f}%" if not summ.empty else "—")

if summ.empty:
    st.success("No hay artículos con precios distintos con estos filtros. 🎉")
    st.stop()

# ---------------------------------------------------------------- 1. regla
st.subheader("1 · Elegí el precio para cada artículo")
REGLAS = {"stock": "Igualar al precio de los talles CON STOCK", **REGLAS}
c1, c2 = st.columns([2.2, 1])
regla = c1.radio("Regla para todos", list(REGLAS), format_func=REGLAS.get, horizontal=True, key="sinc_regla",
                 help="Con stock: Producteca solo actualiza precios de variantes con stock, así que ese es el precio correcto "
                      "y los talles sin stock quedan desactualizados.")
sin_stock_regla = "Mayor"
if regla == "stock":
    sin_stock_regla = c2.selectbox("Si ningún talle tiene stock", ["Mayor", "No tocar"], key="sinc_sinstock",
                                   help="Artículos donde todas las variantes están sin stock: no hay precio de referencia.")


def _fmt(gd):
    out = []
    for v, gv in gd.groupby("precio_cmp"):
        n, con = len(gv), int((gv["stock"].fillna(0) > 0).sum())
        out.append(f"${v:,.0f}".replace(",", ".") + (f" ×{n}" if n > 1 else "") + (f" 📦{con}" if con else " ∅"))
    return " / ".join(out)


det["_con_stock"] = det["stock"].fillna(0) > 0
summ["precios"] = summ["grupo"].map({k: _fmt(gd) for k, gd in det.groupby("grupo")})
pst = det[det["_con_stock"]].groupby("grupo")["precio_cmp"]
summ["n_precios_stock"] = summ["grupo"].map(pst.nunique()).fillna(0).astype(int)
summ["precio_stock"] = summ["grupo"].map(pst.max())
summ["criterio"] = ""
if regla == "stock":
    summ["precio_objetivo"] = summ["precio_stock"]
    summ.loc[summ["n_precios_stock"] == 1, "criterio"] = "📦 precio con stock"
    multi = summ["n_precios_stock"] > 1
    summ.loc[multi, "criterio"] = "⚠️ con stock hay 2+ precios → mayor"
    sin = summ["n_precios_stock"] == 0
    if sin_stock_regla == "Mayor":
        summ.loc[sin, "precio_objetivo"] = summ.loc[sin, "max"]
        summ.loc[sin, "criterio"] = "∅ sin stock → mayor"
    else:
        summ.loc[sin, "criterio"] = "∅ sin stock → no se toca"
else:
    summ["precio_objetivo"] = {"max": summ["max"], "min": summ["min"], "moda": summ["moda"]}.get(
        regla, pd.Series([None] * len(summ), index=summ.index, dtype="float"))
summ.insert(0, "igualar", summ["precio_objetivo"].notna())
if regla == "stock":
    a, b, c = (int((summ["n_precios_stock"] == 1).sum()), int((summ["n_precios_stock"] > 1).sum()),
               int((summ["n_precios_stock"] == 0).sum()))
    st.caption(f"📦 **{a}** con un precio claro en los talles con stock · ⚠️ **{b}** con stock a 2+ precios (revisalos) · "
               f"∅ **{c}** sin ningún talle con stock. En *Precios actuales*: 📦N = variantes con stock a ese precio, "
               "∅ = todas sin stock.")
cols = ["igualar", "foto"] + (["marca"] if len(claves) > 1 else []) + \
       ["titulo", "modelo_color", "productos", "variantes", "precios", "min", "max", "dif_%", "precio_objetivo"] + \
       (["criterio"] if regla == "stock" else []) + ["grupo"]
ed = st.data_editor(
    summ[cols], hide_index=True, width="stretch", row_height=50, height=min(40 + 52 * len(summ), 460),
    key=f"sinc_sum_{how}_{campo}_{regla}_{sin_stock_regla}_{texto}_{min_diff}_{alcance}_{solo_stock}_{len(summ)}",
    disabled=[c for c in cols if c not in ("igualar", "precio_objetivo")],
    column_config={
        "igualar": st.column_config.CheckboxColumn("Igualar", width="small"),
        "foto": st.column_config.ImageColumn("", width="small"),
        "titulo": st.column_config.TextColumn("Producto", width="large"),
        "precios": st.column_config.TextColumn("Precios actuales", width="medium"),
        "min": st.column_config.NumberColumn("Mín.", format="localized"),
        "max": st.column_config.NumberColumn("Máx.", format="localized"),
        "precio_objetivo": st.column_config.NumberColumn(f"{CAMPOS[campo]} a aplicar", format="localized", min_value=0),
        "criterio": st.column_config.TextColumn("Criterio", width="medium"),
        "grupo": None,
    },
)
st.caption("Podés cambiar el **precio a aplicar** de cada artículo o destildar *Igualar* en los que no quieras tocar.")
st.download_button("⬇️ Excel de artículos con precios distintos",
                   to_xlsx(det[["marca", "titulo", "estado", "sku", "modelo_color", "talle", "stock", "precio",
                                "precio_tachado", "url"]].sort_values(["marca", "titulo", "sku"])),
                   file_name=f"precios_distintos_shopify_{datetime.now():%Y%m%d_%H%M}.xlsx")

# ---------------------------------------------------------------- 2. detalle
sel = ed[ed["igualar"]]
obj = dict(zip(sel["grupo"], sel["precio_objetivo"]))
d = det[det["grupo"].isin(obj)].copy()
d["nuevo"] = d["grupo"].map(obj)
d["aplicar"] = d["nuevo"].notna() & (d["nuevo"].round(2) != d[campo].round(2))

st.subheader("2 · Revisá variante por variante")
tach = "No tocar"
if campo == "precio":
    tach = st.radio("¿Y el precio tachado?", ["No tocar", "Igualar también al mayor tachado del grupo",
                                              "Quitarlo si queda menor o igual al precio nuevo"],
                    index=2, horizontal=True, key="sinc_tach",
                    help="Si subís el precio y el tachado queda por debajo, Shopify no muestra el descuento.")
tach_max = det.groupby("grupo")["precio_tachado"].max()
d["tachado_nuevo"] = d["precio_tachado"]
if tach.startswith("Igualar"):
    d["tachado_nuevo"] = d["grupo"].map(tach_max)
if campo == "precio" and tach != "No tocar":
    invalido = d["tachado_nuevo"].notna() & (d["tachado_nuevo"] <= d["nuevo"])
    d.loc[invalido, "tachado_nuevo"] = None
    cambia_t = ~((d["tachado_nuevo"].fillna(-1).round(2)) == (d["precio_tachado"].fillna(-1).round(2)))
    d["aplicar"] = d["aplicar"] | (cambia_t & d["nuevo"].notna())

st.caption("Por defecto se tildan solo las variantes que cambian. Podés editar el valor nuevo de una variante puntual.")
dcols = ["aplicar"] + (["marca"] if len(claves) > 1 else []) + \
        ["titulo", "sku", "talle", "estado", "stock", "precio", "precio_tachado", "nuevo"] + \
        (["tachado_nuevo"] if campo == "precio" and tach != "No tocar" else []) + ["url"]
vista = d.sort_values(["titulo", "sku"])
vista = vista.assign(estado=vista["estado"].map(lambda x: ESTADOS.get(x, x)))
sig = hash(tuple(sorted((k, float(v) if pd.notna(v) else -1) for k, v in obj.items())))
ed2 = st.data_editor(
    vista[dcols + ["variant_id", "product_id", "tienda"]], hide_index=True, width="stretch",
    height=min(40 + 36 * len(vista), 520), key=f"sinc_det_{sig}_{how}_{campo}_{tach}",
    column_order=dcols,
    disabled=[c for c in dcols if c not in ("aplicar", "nuevo", "tachado_nuevo")],
    column_config={
        "aplicar": st.column_config.CheckboxColumn("Aplicar", width="small"),
        "titulo": st.column_config.TextColumn("Producto", width="large"),
        "precio": st.column_config.NumberColumn("Precio actual", format="localized"),
        "precio_tachado": st.column_config.NumberColumn("Tachado actual", format="localized"),
        "nuevo": st.column_config.NumberColumn(f"{CAMPOS[campo]} nuevo", format="localized", min_value=0),
        "tachado_nuevo": st.column_config.NumberColumn("Tachado nuevo", format="localized", min_value=0),
        "url": st.column_config.LinkColumn("Link", display_text="ver"),
    },
)

todo = ed2[ed2["aplicar"] & ed2["nuevo"].notna() & (ed2["nuevo"] > 0)].copy()
if campo == "precio_tachado":
    malos = todo[todo["nuevo"] <= todo["precio"]]
    if not malos.empty:
        st.warning(f"{len(malos)} variantes quedarían con el tachado ≤ al precio (Shopify no lo muestra): se omiten.")
    todo = todo[todo["nuevo"] > todo["precio"]]
if campo == "precio" and tach != "No tocar":
    inval = todo["tachado_nuevo"].notna() & (todo["tachado_nuevo"] <= todo["nuevo"])
    todo.loc[inval, "tachado_nuevo"] = None
if todo.empty:
    st.info("No hay variantes para cambiar.")
    st.stop()

f2 = lambda x: None if x is None or pd.isna(x) else f"{float(x):.2f}"  # noqa: E731
sube = int((todo["nuevo"] > todo[campo].fillna(0)).sum())
baja = int((todo["nuevo"] < todo[campo].fillna(0)).sum())
st.divider()
c1, c2 = st.columns([2, 1], vertical_alignment="center")
ok = c1.checkbox(f"Confirmo cambiar {len(todo)} variantes de {todo['product_id'].nunique()} productos "
                 f"({sube} suben · {baja} bajan)", key=f"sinc_ok_{len(todo)}")
if c2.button(f"⚖️ Igualar {len(todo)} variantes", type="primary", disabled=not ok, key="sinc_go", width="stretch"):
    for k, gk in todo.groupby("tienda"):
        filas = []
        for pid, gp in gk.groupby("product_id"):
            antes, despues = [], []
            for _, r in gp.iterrows():
                if campo == "precio":
                    a = {"id": r["variant_id"], "price": f2(r["precio"])}
                    b = {"id": r["variant_id"], "price": f2(r["nuevo"])}
                    if tach != "No tocar":
                        a["compareAtPrice"], b["compareAtPrice"] = f2(r["precio_tachado"]), f2(r["tachado_nuevo"])
                else:
                    a = {"id": r["variant_id"], "compareAtPrice": f2(r["precio_tachado"])}
                    b = {"id": r["variant_id"], "compareAtPrice": f2(r["nuevo"])}
                antes.append(a)
                despues.append(b)
            filas.append({"id": pid, "label": gp["titulo"].iloc[0], "antes": antes, "despues": despues})
        nom = corto(todas[k]["nombre"])
        st.markdown(f"**{nom}**")
        res = ops.aplicar(k, "precios", filas,
                          f"{nom}: igualar {CAMPOS[campo].lower()} ({REGLAS[regla].lower()}) en {len(gk)} variantes",
                          progress=progreso(f"Igualando {nom}…"))
        ops.mostrar_resultado(res)
    st.caption("Guardado en **Historial**: desde ahí podés deshacerlo.")
