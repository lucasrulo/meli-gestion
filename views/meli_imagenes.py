import hashlib
from datetime import datetime

import pandas as pd
import streamlit as st

from meli import historial
from meli import meli_fotos as mf
from meli import shop_ops as ops
from meli.api import MeliError
from meli.auth import get_token_manager
from meli.bulk import run_bulk
from meli.catalog import match, multiget
from meli.theme import hero
from meli.ui import catalog_index, pick_account, show_results

st.session_state["_page"] = "meli_imagenes"
hero("Imágenes MeLi", "Agregá una misma imagen (ej. la tabla de talles) a muchas publicaciones de una vez.", "MELI · IMÁGENES")
client = pick_account()
index = catalog_index(client)
alias = get_token_manager().accounts().get(client.user_id, {}).get("alias") or client.user_id

ix = index.drop_duplicates("item_id").copy()
skus = index.groupby("item_id")["sku"].apply(lambda s: ", ".join(sorted({str(x) for x in s if x}))[:60])
ix["skus"] = ix["item_id"].map(skus)

st.caption("La imagen se sube una sola vez a MeLi y se agrega a cada publicación (y a todas sus variantes). "
           "Las publicaciones que ya tienen el máximo de fotos de su categoría se omiten. Se puede deshacer desde Historial.")

# ---- 1. imagen
c1, c2 = st.columns([1.3, 1])
up = c1.file_uploader("1 · Imagen (JPG o PNG, ideal 1200×1200 o más)", type=["jpg", "jpeg", "png"], key="mi_up")
pos = c2.radio("Posición", ["Al final", "Como segunda foto"], key="mi_pos",
               help="La primera foto es la portada: no conviene que sea la tabla de talles.")
if up:
    c2.image(up, width=200)

# ---- 2. publicaciones
st.markdown("**2 · Publicaciones**")
modo = st.segmented_control("Elegir por", ["Categoría", "Pegar códigos"], default="Categoría", key="mi_modo") or "Categoría"
estados = st.multiselect("Estados", ["active", "paused"], ["active"], key="mi_est")
base = ix[ix["estado"].isin(estados)]
if modo == "Categoría":
    cats = sorted(base["categoria"].dropna().unique())
    with st.spinner("Leyendo nombres de categorías…"):
        nombres = {c: mf.nombre_categoria(client, c) for c in cats}
    conteo = base.groupby("categoria")["item_id"].nunique().to_dict()
    elegidas = st.multiselect("Categorías", cats, key="mi_cats",
                              format_func=lambda c: f"{nombres.get(c, c)} ({conteo.get(c, 0)})",
                              placeholder="Ej.: Zapatillas, Botines, Ojotas…")
    q = st.text_input("Además, el título contiene (opcional)", key="mi_q", placeholder="ej: running")
    sel = base[base["categoria"].isin(elegidas)]
    if q:
        sel = sel[sel["titulo"].str.contains(q, case=False, regex=False, na=False)]
else:
    txt = st.text_area("Modelo-color, SKU o ID MLA (uno por línea)", key="mi_cod", height=110)
    claves = [x for x in txt.splitlines() if x.strip()]
    if claves:
        m = match(base, claves, "empieza|todo")
        falt = m[m["item_id"].isna()]["clave"].tolist()
        if falt:
            st.warning(f"No encontré {len(falt)}: " + ", ".join(falt[:30]))
        sel = base[base["item_id"].isin(set(m["item_id"].dropna()))]
    else:
        sel = base.iloc[0:0]

if sel.empty:
    st.info("Elegí categorías o pegá códigos para ver las publicaciones.")
    st.stop()

v = sel[["item_id", "titulo", "skus", "categoria", "estado", "permalink"]].copy()
v.insert(0, "✔", True)
ed = st.data_editor(v, hide_index=True, width="stretch", key=f"mi_ed_{len(v)}_{hash(tuple(v['item_id']))}",
                    height=min(40 + 36 * len(v), 420), disabled=[c for c in v.columns if c != "✔"],
                    column_order=["✔", "titulo", "skus", "estado", "permalink"],
                    column_config={"titulo": st.column_config.TextColumn("Publicación", width="large"),
                                   "permalink": st.column_config.LinkColumn("Link", display_text="ver")})
ids = ed.loc[ed["✔"], "item_id"].tolist()
st.caption(f"**{len(ids)}** publicaciones tildadas.")

# ---- 3. aplicar
c1, c2 = st.columns([2, 1], vertical_alignment="center")
ok = c1.checkbox(f"Confirmo agregar la imagen a {len(ids)} publicación(es)", key=f"mi_ok_{len(ids)}")
if c2.button("📤 Agregar imagen", type="primary", disabled=not (ok and up and ids), key="mi_go", width="stretch"):
    datos = up.getvalue()
    kh = f"mi_pic_{client.user_id}_{hashlib.md5(datos).hexdigest()}"
    try:
        if kh not in st.session_state:  # se sube una sola vez aunque reintentes
            with st.spinner("Subiendo la imagen a MercadoLibre…"):
                st.session_state[kh] = mf.subir_imagen(client, datos, up.name, up.type or "image/jpeg")
    except MeliError as e:
        st.error(f"MeLi rechazó la imagen: {e}")
        st.stop()
    pic = st.session_state[kh]
    with st.spinner("Leyendo las fotos actuales…"):
        items = {it["id"]: it for it in multiget(client, ids)}
    filas, log = [], []
    for iid in ids:
        it = items.get(iid)
        if not it:
            continue
        antes = mf.estado_fotos(it)
        filas.append({"item_id": iid, "titulo": it.get("title"), "fotos_antes": len(antes["pictures"]),
                      "_antes": antes, "_max": mf.max_fotos(client, it.get("category_id"))})

    def job(r):
        if pic in r["_antes"]["pictures"]:
            raise RuntimeError("Ya tiene esta imagen")
        if len(r["_antes"]["pictures"]) >= r["_max"]:
            raise RuntimeError(f"Ya tiene el máximo de fotos ({r['_max']})")
        nuevo = mf.con_imagen(r["_antes"], pic, "segunda" if pos.startswith("Como") else "final")
        mf.poner_fotos(client, r["item_id"], nuevo)
        log.append({"id": r["item_id"], "label": r["titulo"], "antes": r["_antes"], "despues": nuevo, "ok": True, "error": ""})

    res = run_bulk(filas, job, label="Agregando imagen")
    historial.registrar("MeLi", alias, "meli_fotos", f"{alias}: agregar «{up.name}» a {len(log)} publicaciones", log,
                        {"user_id": client.user_id, "picture_id": pic})
    show_results(res.drop(columns=["_antes", "_max"], errors="ignore"), f"imagen_meli_{datetime.now():%Y%m%d_%H%M}.xlsx")
    st.caption("Guardado en **Historial**: desde ahí podés deshacerlo (vuelve las fotos como estaban).")
