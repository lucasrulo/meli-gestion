import pandas as pd
import streamlit as st

from meli import historial as hs
from meli import shop_ops as ops
from meli.auth import get_token_manager
from meli.shopify import stores
from meli.theme import hero

hero("Historial", "Todos los cambios masivos con su antes y después. Elegí uno y deshacelo si hace falta.", "CONTROL")

ops_ = hs.listar()
if not ops_:
    st.info("Todavía no hay cambios registrados. Se registran los de Catálogo Shopify, SEO y calidad, "
            "Precios omnicanal / Análisis de precios y Contenido SEO.")
    st.stop()

tiendas = {k: v["nombre"] for k, v in stores().items()}
cuentas = {uid: a.get("alias") or uid for uid, a in get_token_manager().accounts().items()}
df = pd.DataFrame(ops_)
for c in ("deshecha_por", "deshace"):
    if c not in df:
        df[c] = ""
    df[c] = df[c].map(lambda x: x if isinstance(x, str) else "")
df["donde"] = df.apply(lambda r: tiendas.get(r["tienda"]) or cuentas.get(str(r["tienda"])) or r["tienda"], axis=1)
df["accion_txt"] = df["accion"].map(lambda a: ops.NOMBRES.get(a, a))
df["estado"] = df.apply(lambda r: "↩️ deshecho" if r.get("deshecha_por") else ("🔁 deshacer" if r.get("deshace") else
                        ("✅" if r["ok"] == r["total"] else f"⚠️ {r['total'] - r['ok']} error")), axis=1)

f1, f2, f3 = st.columns(3)
canal = f1.multiselect("Canal", sorted(df["canal"].unique()), key="hs_canal")
donde = f2.multiselect("Tienda / cuenta", sorted(df["donde"].unique()), key="hs_donde")
q = f3.text_input("Buscar", key="hs_q")
v = df
if canal:
    v = v[v["canal"].isin(canal)]
if donde:
    v = v[v["donde"].isin(donde)]
if q:
    v = v[v["descripcion"].str.contains(q, case=False, regex=False)]

st.dataframe(v[["fecha", "canal", "donde", "accion_txt", "descripcion", "ok", "total", "estado", "usuario"]],
             hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row", key="hs_tab",
             height=min(40 + 36 * len(v), 420),
             column_config={"fecha": "Fecha", "donde": "Tienda/cuenta", "accion_txt": "Acción",
                            "descripcion": st.column_config.TextColumn("Descripción", width="large"),
                            "ok": "OK", "total": "Total", "estado": "Estado", "usuario": "Usuario"})
if v.empty:
    st.stop()
rows = (st.session_state.get("hs_tab") or {}).get("selection", {}).get("rows", [])
ids = list(v["id"])
if rows and st.session_state.get("_hs_last") != ids[rows[0]]:
    st.session_state["_hs_last"] = st.session_state["hs_sel"] = ids[rows[0]]
lab = v.set_index("id")
op_sel = st.selectbox("Operación (o tocá una fila de la tabla)", ids, key="hs_sel",
                      format_func=lambda i: f"{lab.loc[i, 'fecha']} · {lab.loc[i, 'accion_txt']} · {lab.loc[i, 'descripcion']}"[:140])
r = lab.loc[op_sel].copy()
r["id"] = op_sel
try:
    e = hs.detalle(r["id"])
except Exception as ex:  # noqa: BLE001
    st.error(f"No pude leer el detalle: {ex}")
    st.stop()


def _fmt(x):
    if isinstance(x, list):
        return ", ".join(str(i.get("price") or i.get("compareAtPrice") or i) if isinstance(i, dict) else str(i) for i in x)[:200]
    if isinstance(x, dict):
        return " · ".join(f"{k}: {str(v)[:80]}" for k, v in x.items())[:300]
    return "" if x is None else str(x)[:300]


st.markdown(f"#### {r['accion_txt']} · {r['donde']} · {r['fecha']}")
st.caption(e.get("descripcion", ""))
det = pd.DataFrame([{"Producto": f.get("label") or f.get("id"), "Antes": _fmt(f.get("antes")),
                     "Después": _fmt(f.get("despues")), "Resultado": "OK" if f.get("ok") else f"ERROR: {f.get('error')}"}
                    for f in e.get("filas", [])])
st.dataframe(det, hide_index=True, width="stretch", height=min(40 + 36 * len(det), 380))

inv = ops.inversa(e)
if r.get("deshecha_por"):
    st.info("Esta operación ya fue deshecha.")
elif r.get("deshace"):
    st.info("Esta operación es un «deshacer» de otra; no se puede deshacer de nuevo desde acá.")
elif not inv:
    st.warning("Esta operación no se puede deshacer automáticamente (ej. fotos quitadas o atributos de MeLi).")
else:
    acc, filas, _ = inv
    st.markdown(f"**Deshacer** vuelve {len(filas)} elemento(s) a como estaban antes "
                f"({ops.NOMBRES.get(acc, acc).lower()}).")
    c1, c2 = st.columns([2, 1], vertical_alignment="center")
    ok = c1.checkbox("Confirmo deshacer esta operación", key=f"hs_ok_{r['id']}")
    if c2.button("↩️ Deshacer", type="primary", disabled=not ok, key=f"hs_go_{r['id']}", width="stretch"):
        bar = st.progress(0.0, text="Deshaciendo…")
        res = ops.deshacer(e, progress=lambda p: bar.progress(min(p, 1.0), text=f"Deshaciendo… {p * 100:.0f}%"))
        ops.mostrar_resultado(res)
        st.caption("Recargá la página para ver el historial actualizado.")
