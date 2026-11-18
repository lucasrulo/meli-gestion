"""MeLi ↔ Shopify: copiar / editar descripciones por modelo-color entre los dos canales (con Excel o directo)."""
import io
from datetime import datetime

import pandas as pd
import streamlit as st

from meli import contenido as ct
from meli import shopify as sh
from meli.api import MeliError
from meli.auth import get_token_manager
from meli.bulk import run_bulk
from meli.inconsistencias import strip_size
from meli.theme import hero
from meli.ui import catalog_index, pick_account, show_results

hero("Descripciones entre canales", "Traé la descripción de MeLi o de Shopify y cargala en el otro canal, por modelo-color. "
     "Con Excel (para BUSCARV) o directo.", "MELI ↔ SHOPIFY · CONTENIDO")
client = pick_account()
index = catalog_index(client)

ix = index.drop_duplicates("item_id").copy()
for c in ("familia", "categoria"):
    if c not in ix:
        ix[c] = None
ix["pub"] = (ix["familia"].fillna("") + " · " + ix["categoria"].fillna("")).where(ix["familia"].notna(), ix["item_id"])
pubs = ix.groupby("pub").agg(rep=("item_id", "first"), estado=("estado", "first"),
                             item_ids=("item_id", lambda s: ",".join(s))).reset_index()


def analizadas() -> pd.DataFrame | None:   # mismo análisis que «Descripciones y ficha MeLi» (se comparte)
    return st.session_state.get(f"cont_{client.user_id}")


tab_xl = st.container()
with st.expander("📥 Descripciones de MeLi leídas: " + (f"{len(analizadas())} publicaciones" if analizadas() is not None
                                                     else "ninguna todavía"), expanded=analizadas() is None):
    st.caption("Para traer descripciones **de MeLi** hay que leerlas primero (1–3 min según el catálogo).")
    est_l = st.multiselect("Estados", ["active", "paused"], ["active"], key="xl_est_leer")
    sel_l = pubs[pubs["estado"].isin(est_l)]
    if st.button(f"📥 Leer descripciones de {len(sel_l)} publicaciones", key="xl_leer", type="primary"):
        bar = st.progress(0.0, text="Leyendo descripciones de MeLi…")
        try:
            res = ct.analyze(client, sel_l["rep"].tolist(), progress=lambda p: bar.progress(p))
        except MeliError as e:
            st.error(str(e))
            st.stop()
        bar.empty()
        res = res.merge(sel_l[["rep", "pub", "item_ids"]], left_on="item_id", right_on="rep", how="left")
        res["nombre"] = res["pub"]
        prev = analizadas()
        if prev is not None:
            res = pd.concat([prev[~prev["pub"].isin(res["pub"])], res], ignore_index=True)
        st.session_state[f"cont_{client.user_id}"] = res
        st.rerun()

def _es_html(t: str) -> bool:
    t = str(t or "")
    return "<" in t and ">" in t and any(x in t.lower() for x in ("<p", "<br", "<ul", "<li", "<div", "<h", "<strong", "<b>"))


@st.cache_data(ttl=1800, show_spinner=False)
def _shop_desc(tiendas: tuple[str, ...], nonce) -> pd.DataFrame:
    """Productos Shopify por modelo-color: tienda, product_id, título, descripción (HTML) y SEO."""
    from meli.shop_bulk import catalogo
    rows = []
    for t in tiendas:
        try:
            P_, V_, _, _ = catalogo(t)
        except sh.ShopifyError:
            continue
        info = P_.set_index("product_id")
        vv = V_[V_["sku"].fillna("") != ""].copy()
        vv["modelo_color"] = vv["sku"].map(strip_size)
        for (pid, mc), _g in vv.groupby(["product_id", "modelo_color"]):
            if pid not in info.index or not mc:
                continue
            p = info.loc[pid]
            rows.append({"modelo_color": mc, "tienda": t, "product_id": pid, "producto_shopify": p["titulo"],
                         "html": p["descripcion_html"] or "", "seo_title": p["seo_title"] or "",
                         "seo_description": p["seo_description"] or ""})
    return pd.DataFrame(rows, columns=["modelo_color", "tienda", "product_id", "producto_shopify", "html",
                                       "seo_title", "seo_description"])


with tab_xl:
    st.markdown("1. Elegí **de dónde traer** la descripción y **dónde cargarla** · 2. Bajá el Excel (una fila por "
                "**modelo-color**, ideal para BUSCARV) · 3. Completá/corregí **descripcion_nueva** (las vacías no se "
                "tocan) · 4. Subilo, revisá y aplicá.")
    alias = get_token_manager().accounts().get(client.user_id, {}).get("alias")
    tiendas_x = tuple(sh.stores_for_meli(alias)) if sh.stores() else ()
    c1, c2, c3 = st.columns([1, 1, 1.2])
    origen = c1.segmented_control("Traer de", ["MeLi", "Shopify"], default="MeLi", key="xl_origen") or "MeLi"
    destino = c2.segmented_control("Cargar en", ["Shopify", "MeLi", "Ambos"],
                                   default="Shopify" if origen == "MeLi" else "MeLi", key="xl_destino") or "Shopify"
    alcance = c3.selectbox("Modelos a incluir", ["Los que están en MeLi y Shopify", "Todos los de MeLi",
                                                 "Todos los de Shopify"], key="xl_alc")
    if not tiendas_x and (origen == "Shopify" or destino != "MeLi"):
        st.warning("No hay una tienda Shopify asociada a esta cuenta de MeLi (ver **Configuración → Cuentas y tiendas**).")

    # ---- MeLi por modelo-color: publicaciones + descripción (de lo analizado)
    mi = index[["item_id", "sku", "titulo", "estado"]].copy()
    mi = mi[mi["sku"].fillna("") != ""]
    mi["modelo_color"] = mi["sku"].astype(str).map(strip_size)
    mi["pub"] = mi["item_id"].map(ix.set_index("item_id")["pub"])
    meli_mc = (mi.groupby("modelo_color")
               .agg(producto_meli=("titulo", "first"), item_ids=("item_id", lambda s: ",".join(sorted(set(s)))),
                    pub=("pub", "first"))
               .reset_index())
    df = analizadas()
    desc_pub = df.set_index("pub")["descripcion"].to_dict() if df is not None and not df.empty else {}
    meli_mc["desc_meli"] = meli_mc["pub"].map(desc_pub)
    if origen == "MeLi" and not desc_pub:
        st.info("Para traer las descripciones de MeLi primero tocá **📥 Leer descripciones** (arriba). "
                "(las publicaciones no analizadas salen con la descripción vacía).")

    # ---- Shopify por modelo-color
    shop = pd.DataFrame(columns=["modelo_color", "tienda", "product_id", "producto_shopify", "html", "seo_title",
                                 "seo_description"])
    if tiendas_x:
        with st.spinner("Leyendo productos de Shopify…"):
            shop = _shop_desc(tiendas_x, st.session_state.get("xl_nonce", 0))
    shop_mc = (shop.groupby("modelo_color")
               .agg(producto_shopify=("producto_shopify", "first"), html=("html", "first"),
                    productos_shopify=("product_id", "nunique"))
               .reset_index())
    shop_mc["desc_shopify"] = shop_mc["html"].map(sh.html_to_text)

    how = {"Los que están en MeLi y Shopify": "inner", "Todos los de MeLi": "left",
           "Todos los de Shopify": "right"}[alcance]
    base = meli_mc.merge(shop_mc, on="modelo_color", how=how)
    base["producto"] = base["producto_meli"].fillna(base["producto_shopify"])
    base["publicaciones_meli"] = base["item_ids"].fillna("").map(lambda s: len([x for x in s.split(",") if x]))
    base["productos_shopify"] = base["productos_shopify"].fillna(0).astype(int)
    base["desc_meli"] = base["desc_meli"].fillna("")
    base["desc_shopify"] = base["desc_shopify"].fillna("")
    precompletar = st.checkbox(f"Precompletar **descripcion_nueva** con la de {origen}", value=True, key="xl_pre",
                               help="Así podés copiar de un canal al otro directamente, o corregir antes de subir.")
    base["descripcion_nueva"] = base["desc_meli" if origen == "MeLi" else "desc_shopify"] if precompletar else ""
    cols_x = ["modelo_color", "producto", "publicaciones_meli", "productos_shopify", "desc_meli", "desc_shopify",
              "descripcion_nueva"]
    base = base[cols_x].sort_values("modelo_color").reset_index(drop=True)

    m1, m2, m3 = st.columns(3)
    m1.metric("Modelo-color", len(base))
    m2.metric(f"Con descripción en {origen}",
              int((base["desc_meli" if origen == "MeLi" else "desc_shopify"].str.strip() != "").sum()))
    m3.metric("Destino", destino)
    buf = io.BytesIO()
    base.to_excel(buf, index=False)
    st.download_button("⬇️ Bajar Excel de descripciones (por modelo-color)", buf.getvalue(),
                       file_name=f"descripciones_{origen.lower()}_a_{destino.lower()}_{datetime.now():%Y%m%d}.xlsx")

    fuente = st.radio("¿Qué aplico?", ["Subir el Excel completado", f"Directo: copiar de {origen} sin Excel"],
                      horizontal=True, key="xl_fuente")
    x = None
    if fuente.startswith("Subir"):
        up = st.file_uploader("Subir Excel completado", type=["xlsx"], key="cont_up")
        if up:
            x = pd.read_excel(up, dtype=str).fillna("")
            x.columns = [str(c).strip().lower() for c in x.columns]
            if not {"modelo_color", "descripcion_nueva"} <= set(x.columns):
                st.error("El Excel necesita las columnas **modelo_color** y **descripcion_nueva**.")
                x = None
    else:
        x = base[["modelo_color", "producto", "descripcion_nueva"]].copy()

    if x is not None:
        x["modelo_color"] = x["modelo_color"].str.strip().str.upper()
        x = x[x["descripcion_nueva"].str.strip() != ""].drop_duplicates("modelo_color", keep="last")
        items_mc = meli_mc.set_index("modelo_color")
        prods_mc = shop.groupby("modelo_color")
        filas, faltan = [], []
        for _, r in x.iterrows():
            mc, txt = r["modelo_color"], r["descripcion_nueva"]
            texto = ct.limpiar(sh.html_to_text(txt) if _es_html(txt) else txt)
            html_new = txt if _es_html(txt) else sh.text_to_html(texto)
            hay = False
            if destino in ("MeLi", "Ambos") and mc in items_mc.index:
                for iid in [i for i in str(items_mc.loc[mc, "item_ids"]).split(",") if i]:
                    filas.append({"canal": "MeLi", "modelo_color": mc, "id": iid, "tienda": "",
                                  "desc": texto, "antes": items_mc.loc[mc, "desc_meli"]
                                  if pd.notna(items_mc.loc[mc, "desc_meli"]) else ""})
                hay = True
            if destino in ("Shopify", "Ambos") and mc in prods_mc.groups:
                for _, p in prods_mc.get_group(mc).drop_duplicates("product_id").iterrows():
                    filas.append({"canal": "Shopify", "modelo_color": mc, "id": p["product_id"], "tienda": p["tienda"],
                                  "desc": html_new, "antes": p["html"], "seo_title": p["seo_title"],
                                  "seo_description": p["seo_description"], "producto": p["producto_shopify"]})
                hay = True
            if not hay:
                faltan.append(mc)
        if faltan:
            st.warning(f"{len(faltan)} modelo-color sin publicación/producto en {destino}: " + ", ".join(faltan[:30]))
        fd = pd.DataFrame(filas)
        if fd.empty:
            st.info("No hay nada para aplicar.")
        else:
            fd = fd[fd["desc"].str.strip() != fd["antes"].fillna("").str.strip()]
            prev = (fd.groupby(["modelo_color", "canal"]).agg(destinos=("id", "count"), desc=("desc", "first"))
                    .reset_index())
            prev["largo"] = prev["desc"].map(lambda t: len(sh.html_to_text(t)) if _es_html(t) else len(t))
            st.dataframe(prev, hide_index=True, width="stretch", height=min(40 + 36 * len(prev), 380),
                         column_config={"modelo_color": "Modelo-color", "canal": "Canal",
                                        "destinos": st.column_config.NumberColumn("Publicaciones / productos"),
                                        "desc": st.column_config.TextColumn("Descripción nueva", width="large"),
                                        "largo": st.column_config.NumberColumn("Caract.")})
            n_m, n_s = int((fd["canal"] == "MeLi").sum()), int((fd["canal"] == "Shopify").sum())
            ok = st.checkbox(f"Confirmo actualizar la descripción de {fd['modelo_color'].nunique()} modelo-color "
                             f"({n_m} publicaciones MeLi · {n_s} productos Shopify)", key=f"cont_xl_ok_{len(fd)}")
            if st.button("💾 Aplicar", type="primary", disabled=not ok or fd.empty, key="cont_xl_go"):
                clis: dict[str, sh.ShopifyClient] = {}

                def job(r):
                    if r["canal"] == "MeLi":
                        ct.set_description(client, r["id"], r["desc"])
                    else:
                        cli_ = clis.setdefault(r["tienda"], sh.ShopifyClient(r["tienda"]))
                        cli_.update_product_content(r["id"], description_html=r["desc"])

                res = run_bulk(fd.to_dict("records"), job, label="Guardando descripciones")
                show_results(res[[c for c in ["canal", "modelo_color", "id", "resultado", "error", "procesado"]
                                  if c in res]], f"resultado_excel_desc_{datetime.now():%Y%m%d_%H%M}.xlsx")
                from meli import historial
                okr = res[res["resultado"] == "OK"]
                om = okr[okr["canal"] == "MeLi"]
                if not om.empty:
                    historial.registrar("MeLi", alias or client.user_id, "meli_descripcion",
                                        f"Descripciones MeLi desde {origen} ({om['modelo_color'].nunique()} modelo-color)",
                                        [{"id": r["id"], "label": r["modelo_color"], "antes": r["antes"],
                                          "despues": r["desc"], "ok": True, "error": ""} for _, r in om.iterrows()],
                                        {"user_id": client.user_id})
                os_ = okr[okr["canal"] == "Shopify"]
                for t, g in os_.groupby("tienda"):
                    historial.registrar("Shopify", t, "contenido",
                                        f"Descripciones Shopify desde {origen} ({g['modelo_color'].nunique()} modelo-color)",
                                        [{"id": r["id"], "label": r.get("producto") or r["modelo_color"],
                                          "antes": {"descriptionHtml": r["antes"],
                                                    "seo": {"title": r["seo_title"], "description": r["seo_description"]}},
                                          "despues": {"descriptionHtml": r["desc"],
                                                      "seo": {"title": r["seo_title"], "description": r["seo_description"]}},
                                          "ok": True, "error": ""} for _, r in g.iterrows()])
                if not os_.empty:
                    st.session_state["xl_nonce"] = st.session_state.get("xl_nonce", 0) + 1
