from datetime import datetime

import pandas as pd
import streamlit as st

from meli import clips as cp
from meli.excel import to_xlsx
from meli.theme import hero
from meli.ui import catalog_index, pick_account

st.session_state["_page"] = "clips"
hero("Clips", "Qué publicaciones ya tienen clips (videos verticales) y cuáles conviene grabar, priorizadas por ventas.",
     "CATÁLOGO · VIDEO")
client = pick_account()
index = catalog_index(client)

ix = index.drop_duplicates("item_id").copy()
ix["familia"] = ix.get("familia")
ix["pub"] = ix["familia"].fillna(ix["item_id"]) if "familia" in ix else ix["item_id"]
skus = index.groupby("item_id")["sku"].apply(lambda s: ", ".join(sorted({str(x) for x in s if x}))[:80])
ix["skus"] = ix["item_id"].map(skus)

c1, c2 = st.columns([1, 2])
estados = c1.multiselect("Estados", ["active", "paused"], ["active"], key="clp_est")
calib = c2.text_input("Opcional: ID de una publicación que SÍ tenga clip (ej. MLA123456789)", key="clp_cal",
                      help="Sirve para confirmar el recurso de la API la primera vez. Si no lo sabés, dejalo vacío.")
sel = ix[ix["estado"].isin(estados)]
k = f"clips_{client.user_id}"

if st.button(f"🎬 Relevar clips de {len(sel)} publicaciones", type="primary", key="clp_go"):
    ids = sel.sort_values("stock", ascending=False)["item_id"].tolist()
    prueba = ([calib.strip().upper()] if calib.strip() else []) + ids
    with st.spinner("Detectando el recurso de clips de la API…"):
        ep, log = cp.detectar_endpoint(client, prueba)
    bar = st.progress(0.0, text="Consultando clips…")
    df = cp.relevar(client, ids, ep, progress=lambda p: bar.progress(p, text=f"Consultando clips… {p * 100:.0f}%"))
    bar.empty()
    df = df.merge(sel[["item_id", "pub", "familia", "skus"]], on="item_id", how="left")
    st.session_state[k] = (df, ep, log, datetime.now().strftime("%d/%m %H:%M"))

if k not in st.session_state:
    st.info("Tocá **Relevar clips** para armar el listado.")
    st.stop()

df, ep, log, cuando = st.session_state[k]
with st.expander("Diagnóstico de la API" + (" ✅" if ep else " ⚠️"), expanded=not ep):
    st.caption(f"Recurso usado: `{ep}`" if ep else "Ninguno de los recursos de clips respondió para esta cuenta.")
    st.code("\n".join(log) or "-", language=None)
    if not ep:
        st.warning("MeLi no expuso los clips para esta cuenta por API (o ninguna de las publicaciones probadas tiene clip). "
                   "Probá cargar arriba el ID de una publicación que tenga clip y volvé a relevar. "
                   "Mientras tanto el listado muestra solo el video clásico.")

# ---- por publicación (agrupa las variantes/colores de una misma familia)
g = (df.groupby("pub").agg(titulo=("titulo", "first"), foto=("foto", "first"), items=("item_id", "nunique"),
                           items_con_clip=("publicados", lambda s: int((s > 0).sum())),
                           clips=("clips", "sum"), publicados=("publicados", "sum"), en_revision=("en_revision", "sum"),
                           rechazados=("rechazados", "sum"), video_clasico=("video_clasico", "max"),
                           vendidos=("vendidos", "sum"), stock=("stock", "sum"), skus=("skus", "first"),
                           motivos=("motivos", lambda s: " | ".join(x for x in s if x)[:300]), link=("link", "first"))
     .reset_index())
g["situacion"] = g.apply(lambda r: "✅ Con clip" if r["publicados"] else ("⏳ En revisión" if r["en_revision"] else
                         ("❌ Rechazado" if r["rechazados"] else "🎬 Sin clip")), axis=1)

m = st.columns(4)
m[0].metric("Publicaciones", len(g))
m[1].metric("✅ Con clip publicado", int((g["publicados"] > 0).sum()))
m[2].metric("🎬 Sin clip", int((g["situacion"] == "🎬 Sin clip").sum()))
m[3].metric("❌ Rechazados", int((g["rechazados"] > 0).sum()))
st.caption(f"Relevado {cuando}. Prioridad para grabar: las que más venden y tienen stock, sin clip.")

f1, f2 = st.columns([2, 1])
ver = f1.segmented_control("Ver", ["🎬 Sin clip", "✅ Con clip", "⏳ En revisión", "❌ Rechazado", "Todas"],
                           default="🎬 Sin clip", key="clp_ver") or "Todas"
solo_stock = f2.toggle("Solo con stock", value=True, key="clp_stock")
v = g if ver == "Todas" else g[g["situacion"] == ver]
if solo_stock:
    v = v[v["stock"].fillna(0) > 0]
v = v.sort_values(["vendidos", "stock"], ascending=False)
st.dataframe(v[["foto", "titulo", "situacion", "publicados", "en_revision", "rechazados", "items_con_clip", "items",
                "video_clasico", "vendidos", "stock", "skus", "motivos", "link"]],
             hide_index=True, width="stretch", row_height=56, height=min(40 + 58 * len(v), 640),
             column_config={"foto": st.column_config.ImageColumn("", width="small"),
                            "titulo": st.column_config.TextColumn("Publicación", width="large"),
                            "situacion": "Situación", "publicados": "Clips ✅", "en_revision": "⏳", "rechazados": "❌",
                            "items_con_clip": st.column_config.NumberColumn("Colores con clip"),
                            "items": st.column_config.NumberColumn("Colores"),
                            "video_clasico": st.column_config.CheckboxColumn("Video clásico"),
                            "vendidos": st.column_config.NumberColumn("Vendidos"),
                            "motivos": st.column_config.TextColumn("Motivo de rechazo", width="medium"),
                            "link": st.column_config.LinkColumn("Link", display_text="ver")})
st.download_button("⬇️ Descargar Excel", to_xlsx(g.drop(columns=["foto"]).sort_values("vendidos", ascending=False)),
                   f"clips_{datetime.now():%Y%m%d}.xlsx")
