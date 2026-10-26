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

estados = st.multiselect("Estados", ["active", "paused"], ["active"], key="clp_est")
sel = ix[ix["estado"].isin(estados)]
k = f"clips_{client.user_id}"
st.caption("Se lee la página pública de cada publicación (la API de MeLi no expone clips para cuentas de Argentina). "
           "Tarda ~1 minuto cada 150 publicaciones.")

if st.button(f"🎬 Relevar clips de {len(sel)} publicaciones", type="primary", key="clp_go"):
    ids = sel["item_id"].tolist()
    bar = st.progress(0.0, text="Leyendo publicaciones…")
    df = cp.relevar(client, ids, progress=lambda p: bar.progress(p, text=f"Leyendo publicaciones… {p * 100:.0f}%"))
    bar.empty()
    df = df.merge(sel[["item_id", "pub", "familia", "skus"]], on="item_id", how="left")
    st.session_state[k] = (df, datetime.now().strftime("%d/%m %H:%M"))

if k not in st.session_state:
    st.info("Tocá **Relevar clips** para armar el listado.")
    st.stop()

df, cuando = st.session_state[k]
errs = df[df["error"] != ""]
if len(errs):
    with st.expander(f"⚠️ {len(errs)} publicaciones no se pudieron leer", expanded=len(errs) > len(df) / 2):
        st.dataframe(errs[["item_id", "titulo", "error", "link"]], hide_index=True, width="stretch",
                     column_config={"link": st.column_config.LinkColumn("Link", display_text="ver")})
        if len(errs) > len(df) / 2:
            st.warning("MeLi está bloqueando la lectura desde el servidor de la app. Probá de nuevo en unos minutos; "
                       "si persiste avisame y lo pasamos a correr desde GitHub Actions.")

# ---- por publicación (agrupa las variantes/colores de una misma familia)
def _agg(x: pd.DataFrame) -> pd.Series:
    det = {c["clip_id"]: c for lst in x["clips_det"] for c in lst}
    ids = set(det)
    return pd.Series({
        "titulo": x["titulo"].iloc[0], "foto": x["foto"].iloc[0], "items": x["item_id"].nunique(),
        "items_con_clip": int((x["clips"] > 0).sum()), "clips": len(ids),
        "vistas": int(sum(int(c["vistas"] or 0) for c in det.values())),
        "ultimo_clip": max(x["ultimo_clip"]), "video_clasico": bool(x["video_clasico"].any()),
        "vendidos": int(x["vendidos"].sum()), "stock": int(x["stock"].fillna(0).sum()), "skus": x["skus"].iloc[0],
        "link": x["link"].iloc[0], "error": " | ".join(e for e in x["error"] if e)[:120]})


g = df.groupby("pub").apply(_agg, include_groups=False).reset_index()
g["situacion"] = g.apply(lambda r: "✅ Con clip" if r["clips"] else ("⚠️ Sin leer" if r["error"] else "🎬 Sin clip"), axis=1)

m = st.columns(4)
m[0].metric("Publicaciones", len(g))
m[1].metric("✅ Con clip", int((g["clips"] > 0).sum()))
m[2].metric("🎬 Sin clip", int((g["situacion"] == "🎬 Sin clip").sum()))
m[3].metric("👁️ Vistas de clips", f"{int(g['vistas'].sum()):,}".replace(",", "."))
st.caption(f"Relevado {cuando}. Prioridad para grabar: las que más venden y tienen stock, sin clip.")

f1, f2 = st.columns([2, 1])
ver = f1.segmented_control("Ver", ["🎬 Sin clip", "✅ Con clip", "⚠️ Sin leer", "Todas"],
                           default="🎬 Sin clip", key="clp_ver") or "Todas"
solo_stock = f2.toggle("Solo con stock", value=True, key="clp_stock")
v = g if ver == "Todas" else g[g["situacion"] == ver]
if solo_stock:
    v = v[v["stock"].fillna(0) > 0]
v = v.sort_values(["vendidos", "stock"], ascending=False)
st.dataframe(v[["foto", "titulo", "situacion", "clips", "vistas", "ultimo_clip", "items_con_clip", "items",
                "video_clasico", "vendidos", "stock", "skus", "link"]],
             hide_index=True, width="stretch", row_height=56, height=min(40 + 58 * len(v), 640),
             column_config={"foto": st.column_config.ImageColumn("", width="small"),
                            "titulo": st.column_config.TextColumn("Publicación", width="large"),
                            "situacion": "Situación", "clips": "Clips", "vistas": st.column_config.NumberColumn("Vistas"),
                            "ultimo_clip": "Último clip",
                            "items_con_clip": st.column_config.NumberColumn("Colores con clip"),
                            "items": st.column_config.NumberColumn("Colores"),
                            "video_clasico": st.column_config.CheckboxColumn("Video clásico"),
                            "vendidos": st.column_config.NumberColumn("Vendidos"),
                            "link": st.column_config.LinkColumn("Link", display_text="ver")})
st.download_button("⬇️ Descargar Excel", to_xlsx(g.drop(columns=["foto"]).sort_values("vendidos", ascending=False)),
                   f"clips_{datetime.now():%Y%m%d}.xlsx")
