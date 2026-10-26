from datetime import datetime

import pandas as pd
import streamlit as st

from meli import clips as cp
from meli.excel import to_xlsx
from meli.theme import hero
from meli.ui import catalog_index, pick_account

st.session_state["_page"] = "clips"
hero("Clips y video", "Qué publicaciones ya tienen video/clip y a cuáles conviene hacerle, priorizadas por ventas.",
     "CATÁLOGO · VIDEO")
client = pick_account()
index = catalog_index(client)

ix = index.drop_duplicates("item_id").copy()
if "familia" not in ix:
    ix["familia"] = None
ix["pub"] = ix["familia"].fillna(ix["item_id"])
skus = index.groupby("item_id")["sku"].apply(lambda s: ", ".join(sorted({str(x) for x in s if x}))[:80])
ix["skus"] = ix["item_id"].map(skus)

c1, c2 = st.columns([1.2, 2])
estados = c1.multiselect("Estados", ["active", "paused"], ["active"], key="clp_est")
alcance = c2.radio("Qué actualizar", ["Todo", "Solo las que no tenían video"], key="clp_alc", horizontal=True)
sel = ix[ix["estado"].isin(estados)]
k = f"clips2_{client.user_id}"


def _store():
    from meli.token_store import GitHubTokenStore
    gs = GitHubTokenStore()
    gs.path = f"clips/v2_{client.user_id}.json"
    return gs


if k not in st.session_state:  # último relevamiento guardado (se ve al instante)
    try:
        d, _ = _store().load()
        if d.get("rows"):
            st.session_state[k] = (pd.DataFrame(d["rows"]), d.get("fecha", ""))
    except Exception:  # noqa: BLE001
        pass

prev = st.session_state.get(k, (None, ""))[0]
objetivo = sel
if alcance.startswith("Solo") and prev is not None and not prev.empty:
    objetivo = sel[~sel["item_id"].isin(set(prev.loc[prev["video"] == "con video", "item_id"]))]
n = len(objetivo)
st.caption("Usa la API oficial de **Calidad de publicaciones**: el objetivo «Creá un video» que ves en Central de "
           f"vendedores como «Sin video». {n} publicaciones · ~{max(1, round(n / 400))} min.")

with st.expander("🔧 Probar una publicación"):
    d1, d2 = st.columns([2, 1], vertical_alignment="bottom")
    pid = d1.text_input("ID de publicación de esta cuenta", placeholder="MLA1866105389", key="clp_diag_id")
    if d2.button("Probar", key="clp_diag", disabled=not pid.strip()):
        st.json(cp.diagnostico(client, pid.strip().upper().replace("-", "")))

if st.button(f"🎬 Relevar {n} publicaciones", type="primary", key="clp_go", disabled=not n):
    t0 = datetime.now()
    bar = st.progress(0.0, text="Consultando calidad de publicaciones…")

    def prog(p):
        seg = (datetime.now() - t0).total_seconds()
        resta = seg / p * (1 - p) if p > 0.03 else 0
        bar.progress(p, text=f"Consultando… {p * 100:.0f}%" + (f" · faltan ~{resta:.0f}s" if resta else ""))
    nuevo = cp.relevar(client, objetivo["item_id"].tolist(), progress=prog)
    bar.empty()
    nuevo = nuevo.merge(objetivo[["item_id", "pub", "skus"]], on="item_id", how="left")
    if prev is not None and not prev.empty:
        nuevo = pd.concat([prev[~prev["item_id"].isin(set(nuevo["item_id"]))], nuevo], ignore_index=True)
    cuando = datetime.now().strftime("%d/%m %H:%M")
    st.session_state[k] = (nuevo, cuando)
    try:
        rows = nuevo.to_dict("records")
        _store().update(lambda d: {"fecha": cuando, "rows": rows}, f"clips {client.user_id}")
    except Exception as e:  # noqa: BLE001
        st.caption(f"(No pude guardar el relevamiento: {e})")
    st.toast(f"Listo en {(datetime.now() - t0).total_seconds():.0f}s")

if k not in st.session_state:
    st.info("Tocá **Relevar** para armar el listado. Queda guardado: la próxima vez se ve al instante.")
    st.stop()

df, cuando = st.session_state[k]
df = df[df["item_id"].isin(set(sel["item_id"]))]
errs = df[df["error"].fillna("") != ""]
if len(errs):
    with st.expander(f"⚠️ {len(errs)} publicaciones sin dato de calidad"):
        st.dataframe(errs[["item_id", "titulo", "error"]], hide_index=True, width="stretch")
if not df.empty and (df["video"] == "sin dato").all():
    st.warning("La API de calidad no trae el objetivo de video para esta cuenta. Usá **🔧 Probar una publicación** "
               "con una que tenga clip y mandame la captura de «todas_las_reglas».")


def _agg(x: pd.DataFrame) -> pd.Series:
    con = int((x["video"] == "con video").sum())
    sin = int((x["video"] == "sin video").sum())
    return pd.Series({
        "titulo": x["titulo"].iloc[0], "foto": x["foto"].iloc[0], "colores": x["item_id"].nunique(),
        "con_video": con, "sin_video": sin, "vendidos": int(x["vendidos"].sum()), "stock": int(x["stock"].fillna(0).sum()),
        "calidad": x["calidad"].dropna().mean() if x["calidad"].notna().any() else None, "skus": x["skus"].iloc[0],
        "crear": next((l for l in x["crear_link"] if isinstance(l, str) and l), ""), "link": x["link"].iloc[0]})


g = df.groupby("pub").apply(_agg, include_groups=False).reset_index()
g["situacion"] = g.apply(lambda r: "✅ Con video" if r["con_video"] and not r["sin_video"] else
                         ("🟡 Algunos colores" if r["con_video"] else ("🎬 Sin video" if r["sin_video"] else "❔ Sin dato")),
                         axis=1)

m = st.columns(4)
m[0].metric("Publicaciones", len(g))
m[1].metric("✅ Con video", int((g["situacion"] == "✅ Con video").sum()))
m[2].metric("🟡 Algunos colores", int((g["situacion"] == "🟡 Algunos colores").sum()))
m[3].metric("🎬 Sin video", int((g["situacion"] == "🎬 Sin video").sum()))
st.caption(f"Relevado {cuando}. Prioridad para grabar: las que más venden y tienen stock, sin video.")

f1, f2 = st.columns([2.4, 1])
ver = f1.segmented_control("Ver", ["🎬 Sin video", "🟡 Algunos colores", "✅ Con video", "❔ Sin dato", "Todas"],
                           default="🎬 Sin video", key="clp_ver") or "Todas"
solo_stock = f2.toggle("Solo con stock", value=True, key="clp_stock")
v = g if ver == "Todas" else g[g["situacion"] == ver]
if solo_stock:
    v = v[v["stock"] > 0]
v = v.sort_values(["vendidos", "stock"], ascending=False)
st.dataframe(v[["foto", "titulo", "situacion", "con_video", "colores", "vendidos", "stock", "calidad", "skus", "crear", "link"]],
             hide_index=True, width="stretch", row_height=56, height=min(40 + 58 * len(v), 640),
             column_config={"foto": st.column_config.ImageColumn("", width="small"),
                            "titulo": st.column_config.TextColumn("Publicación", width="large"),
                            "situacion": "Situación", "con_video": st.column_config.NumberColumn("Colores con video"),
                            "colores": "Colores", "vendidos": "Vendidos",
                            "calidad": st.column_config.ProgressColumn("Calidad", min_value=0, max_value=100, format="%d"),
                            "crear": st.column_config.LinkColumn("Crear video", display_text="crear"),
                            "link": st.column_config.LinkColumn("Link", display_text="ver")})
st.download_button("⬇️ Descargar Excel", to_xlsx(g.drop(columns=["foto"]).sort_values("vendidos", ascending=False)),
                   f"videos_{datetime.now():%Y%m%d}.xlsx")
