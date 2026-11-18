import json

import pandas as pd
import streamlit as st

from meli import azure_fotos as az
from meli import contenido as ct
from meli import shop_ops as ops
from meli.config import secret
from meli.shop_ui import ESTADOS, _match_codigos, cargar, colecciones as _colecciones, ejecutar_ui, pick_store, progreso, \
    publicaciones as _publicaciones, selector
from meli.shopify import ShopifyClient, ShopifyError, html_to_text, stores
from meli.excel import to_xlsx
from meli.inconsistencias import strip_size
from meli.theme import hero

hero("Tags y colecciones", "Tags en masa, limpieza de tags sin uso, colecciones y su orden.", "SHOPIFY · COLECCIONES")
tienda = pick_store()
nombre = stores()[tienda]["nombre"]
P, V, M, MF = cargar(tienda)
api_key = secret("ANTHROPIC_API_KEY")

t_tag, t_limp, t_col, t_ord = st.tabs(["🏷️ Tags", "🧹 Limpiar tags", "📚 Ver colecciones", "↕️ Ordenar colección"])


def _filas(sel: pd.DataFrame, antes_col, despues) -> list[dict]:
    return [{"id": r["product_id"], "label": r["titulo"],
             "antes": r[antes_col] if isinstance(antes_col, str) else antes_col(r),
             "despues": despues(r) if callable(despues) else despues} for _, r in sel.iterrows()]



# ================================================================ 2. tags y colecciones
with t_tag:
    modo = st.segmented_control("¿Qué querés hacer?", ["Tags", "Agregar a colección", "Quitar de colección",
                                                        "Crear colección"], default="Tags", key="tag_modo") or "Tags"
    sel = selector(P, "tag", extra_cols=["tags"])
    tags_all = sorted({t for ts in P["tags"] for t in ts})
    if modo == "Tags":
        como = st.radio("Cómo", ["➕ Agregar", "🔁 Reemplazar todos", "➖ Quitar", "🔎 Buscar y reemplazar"],
                        horizontal=True, key="tag_como",
                        help="Agregar: suma a los tags que ya tiene. Reemplazar todos: deja SOLO los que elijas. "
                             "Buscar y reemplazar: cambia una palabra dentro de los tags.")
        en_sel = sorted({t for ts in sel["tags"] for t in ts}) if not sel.empty else tags_all

        def _lista(label: str, key: str, opciones: list[str]) -> list[str]:
            c1, c2 = st.columns(2)
            ex = c1.multiselect(f"{label} (existentes)", opciones, key=f"{key}_ex")
            nv = c2.text_input("…o escribilos (separados por coma)", key=f"{key}_nv")
            return list(dict.fromkeys(ex + [t.strip() for t in nv.split(",") if t.strip()]))

        nuevo_de = None   # función tags actuales -> tags nuevos
        desc = ""
        if como == "➕ Agregar":
            tags = _lista("Tags a agregar", "tag_add", tags_all)
            if tags:
                nuevo_de = lambda ts: list(dict.fromkeys(list(ts) + tags))  # noqa: E731
                desc = f"agregar «{', '.join(tags)}»"
        elif como == "🔁 Reemplazar todos":
            tags = _lista("Tags que van a quedar", "tag_set", tags_all)
            st.caption("⚠️ Se borran todos los tags actuales de los productos tildados y quedan solo estos.")
            if tags:
                nuevo_de = lambda ts: list(tags)  # noqa: E731
                desc = f"reemplazar tags por «{', '.join(tags)}»"
        elif como == "➖ Quitar":
            tags = st.multiselect("Tags a quitar", en_sel, key="tag_rm")
            if tags:
                nuevo_de = lambda ts: [t for t in ts if t not in tags]  # noqa: E731
                desc = f"quitar «{', '.join(tags)}»"
        else:
            c1, c2, c3 = st.columns([1, 1, 1.2], vertical_alignment="bottom")
            buscar = c1.text_input("Buscar", key="tag_bus", placeholder="ej: verano25")
            reempl = c2.text_input("Reemplazar por", key="tag_rep", placeholder="ej: verano26 (vacío = borrar)")
            alcance_b = c3.radio("Buscar en", ["Parte del tag", "Tag completo"], horizontal=True, key="tag_alc")
            if buscar.strip():
                import re as _re
                b_ = buscar.strip()
                patron = _re.compile(_re.escape(b_), _re.I)

                def nuevo_de(ts):
                    out = []
                    for t in ts:
                        if alcance_b == "Tag completo":
                            t2 = reempl.strip() if t.lower() == b_.lower() else t
                        else:
                            t2 = patron.sub(reempl, t).strip(" ,")
                        if t2:
                            out.append(t2)
                    return list(dict.fromkeys(out))
                desc = f"reemplazar «{b_}» por «{reempl}»" if reempl else f"borrar «{b_}» de los tags"
                hits = sorted({t for ts in sel["tags"] for t in ts if patron.search(t)}) if not sel.empty else []
                st.caption("Tags que coinciden: " + (", ".join(f"`{t}`" for t in hits[:40]) if hits else "ninguno"))

        if nuevo_de and not sel.empty:
            prev = sel[["product_id", "titulo", "tags"]].copy()
            prev["nuevos"] = prev["tags"].apply(lambda ts: nuevo_de(list(ts)))
            afect = prev[prev.apply(lambda r: list(r["tags"]) != list(r["nuevos"]), axis=1)]
            st.markdown(f"**{len(afect)}** de {len(prev)} producto(s) cambian.")
            if not afect.empty:
                st.dataframe(afect.assign(tags=afect["tags"].map(", ".join), nuevos=afect["nuevos"].map(", ".join))
                             [["titulo", "tags", "nuevos"]].head(300), hide_index=True, width="stretch",
                             height=min(40 + 36 * len(afect), 320),
                             column_config={"titulo": st.column_config.TextColumn("Producto", width="medium"),
                                            "tags": st.column_config.TextColumn("Tags actuales", width="large"),
                                            "nuevos": st.column_config.TextColumn("Tags nuevos", width="large")})
            if ejecutar_ui("🏷️ Aplicar tags", len(afect), "tag"):
                filas = [{"id": r["product_id"], "label": r["titulo"], "antes": list(r["tags"]), "despues": list(r["nuevos"])}
                         for _, r in afect.iterrows()]
                res = ops.aplicar(tienda, "tags_set", filas, f"{nombre}: {desc} en {len(filas)} productos",
                                  progress=progreso("Tags…"))
                ops.mostrar_resultado(res)
    elif modo in ("Agregar a colección", "Quitar de colección"):
        nk = f"coll_nonce_{tienda}"
        cols = _colecciones(tienda, st.session_state.get(nk, 0))
        manuales = cols[cols["tipo"] == "Manual"]
        if manuales.empty:
            st.info("No hay colecciones manuales en esta tienda (las automáticas se arman por reglas, ej. por tag).")
        else:
            cid = st.selectbox("Colección manual", manuales["id"], key="coll_id",
                               format_func=lambda i: f"{manuales.set_index('id').loc[i, 'titulo']} "
                                                     f"({manuales.set_index('id').loc[i, 'productos']} productos)")
            if not sel.empty and ejecutar_ui("📚 Aplicar", len(sel), "coll"):
                acc = "coleccion_add" if modo == "Agregar a colección" else "coleccion_remove"
                tit = manuales.set_index("id").loc[cid, "titulo"]
                res = ops.aplicar(tienda, acc, _filas(sel, lambda r: None, None),
                                  f"{nombre}: {modo.lower()} «{tit}» ({len(sel)} productos)",
                                  {"collection_id": cid, "coleccion": tit}, progress=progreso("Colección…"))
                ops.mostrar_resultado(res)
                st.session_state[nk] = st.session_state.get(nk, 0) + 1
            st.caption("Shopify procesa el alta/baja en colecciones en segundo plano: puede tardar unos segundos en verse.")
    else:  # crear colección
        c1, c2 = st.columns([1.2, 1])
        titulo_c = c1.text_input("Nombre de la colección", key="cc_tit", placeholder="Ej: Running Hombre")
        tipo_c = c2.radio("Tipo", ["Automática por tag", "Manual con los productos tildados"], key="cc_tipo",
                          horizontal=True)
        tag_c = st.selectbox("Tag que define la colección", tags_all, key="cc_tag") if tipo_c.startswith("Auto") else None
        pubs = _publicaciones(tienda)
        pub_c = st.multiselect("Publicar en", [p["id"] for p in pubs], key="cc_pub",
                               default=[p["id"] for p in pubs if "online" in p["nombre"].lower()][:1],
                               format_func=lambda i: next(p["nombre"] for p in pubs if p["id"] == i))
        listo = bool(titulo_c and (tag_c or (tipo_c.startswith("Manual") and not sel.empty)))
        if st.button("➕ Crear colección", type="primary", disabled=not listo, key="cc_go"):
            cli = ShopifyClient(tienda)
            inp = {"title": titulo_c}
            if tag_c:
                inp["ruleSet"] = {"appliedDisjunctively": False,
                                  "rules": [{"column": "TAG", "relation": "EQUALS", "condition": tag_c}]}
            try:
                d = cli.gql("""mutation($i: CollectionInput!) { collectionCreate(input: $i) {
                                 collection { id handle } userErrors { field message } } }""", {"i": inp},
                            version=ops.COLL_VERSION)["collectionCreate"]
                if d["userErrors"]:
                    raise ShopifyError("; ".join(e["message"] for e in d["userErrors"]))
                cid = d["collection"]["id"]
                if pub_c:
                    cli.gql(ops.M_PUBLISH, {"id": cid, "input": [{"publicationId": p} for p in pub_c]})
                st.success(f"Colección creada: **{titulo_c}** (/collections/{d['collection']['handle']})")
                if tipo_c.startswith("Manual"):
                    res = ops.aplicar(tienda, "coleccion_add", _filas(sel, lambda r: None, None),
                                      f"{nombre}: crear colección «{titulo_c}» con {len(sel)} productos",
                                      {"collection_id": cid, "coleccion": titulo_c}, progress=progreso("Colección…"))
                    ops.mostrar_resultado(res)
                st.session_state[f"coll_nonce_{tienda}"] = st.session_state.get(f"coll_nonce_{tienda}", 0) + 1
            except ShopifyError as e:
                st.error(str(e))



# ================================================================ 2a. limpiar tags sin uso
@st.cache_data(ttl=600, show_spinner=False)
def _reglas_colecciones(key: str, nonce) -> pd.DataFrame:
    q = """query($c: String) { collections(first: 250, after: $c) { pageInfo { hasNextPage endCursor }
             nodes { id title ruleSet { rules { column relation condition } } } } }"""
    cli, rows, cur = ShopifyClient(key), [], None
    while True:
        d = cli.gql(q, {"c": cur}, version=ops.COLL_VERSION)["collections"]
        for n in d["nodes"]:
            for r in ((n.get("ruleSet") or {}).get("rules") or []):
                rows.append({"coleccion": n["title"], "columna": r.get("column"), "relacion": r.get("relation"),
                             "condicion": str(r.get("condition") or "")})
        if not d["pageInfo"]["hasNextPage"]:
            break
        cur = d["pageInfo"]["endCursor"]
    return pd.DataFrame(rows, columns=["coleccion", "columna", "relacion", "condicion"])


with t_limp:
    st.caption("Lista todos los tags de los productos y marca cuáles **no usa ninguna colección automática**. "
               "Ojo: un tag sin colección puede igual servir para filtros del theme, descuentos, apps o reportes — "
               "revisá antes de borrar.")
    try:
        R = _reglas_colecciones(tienda, st.session_state.get(f"coll_nonce_{tienda}", 0))
    except ShopifyError as e:
        st.error(str(e))
        R = pd.DataFrame(columns=["coleccion", "columna", "relacion", "condicion"])
    rt = R[R["columna"] == "TAG"]
    uso = rt.groupby(rt["condicion"].str.strip().str.lower())["coleccion"].apply(
        lambda s_: ", ".join(sorted(set(s_)))).to_dict()
    ex = P[["product_id", "estado", "tags"]].explode("tags").dropna(subset=["tags"])
    if ex.empty:
        st.info("Los productos de esta tienda no tienen tags.")
    else:
        T = (ex.groupby("tags").agg(productos=("product_id", "nunique"),
                                    activos=("estado", lambda s_: int((s_ == "ACTIVE").sum())))
             .reset_index().rename(columns={"tags": "tag"}))
        T["colecciones"] = T["tag"].str.strip().str.lower().map(uso).fillna("")
        T["situacion"] = T["colecciones"].map(lambda c: "✅ En colección" if c else "🧹 Sin colección")
        m1, m2, m3 = st.columns(3)
        m1.metric("Tags distintos", len(T))
        m2.metric("✅ Usados en colecciones", int((T["colecciones"] != "").sum()))
        m3.metric("🧹 Sin colección", int((T["colecciones"] == "").sum()))
        f1, f2, f3 = st.columns([1.3, 1, 1.2])
        ver = f1.radio("Mostrar", ["🧹 Sin colección", "✅ En colección", "Todos"], horizontal=True, key="lt_ver")
        maxp = f2.number_input("Usado en hasta N productos", min_value=0, value=0, step=1, key="lt_max",
                               help="0 = sin límite. Ej.: 3 para ver tags casi sin uso (errores de tipeo, viejos).")
        q = f3.text_input("Buscar tag", key="lt_q")
        v = T if ver == "Todos" else T[T["situacion"] == ver]
        if maxp:
            v = v[v["productos"] <= maxp]
        if q:
            v = v[v["tag"].str.contains(q, case=False, regex=False)]
        v = v.sort_values(["productos", "tag"]).copy()
        v.insert(0, "Borrar", False)
        ed = st.data_editor(v, hide_index=True, width="stretch", key=f"lt_ed_{len(v)}_{hash(tuple(v['tag']))}",
                            height=min(40 + 36 * len(v), 460), disabled=["tag", "productos", "activos", "colecciones",
                                                                         "situacion"],
                            column_order=["Borrar", "tag", "situacion", "productos", "activos", "colecciones"],
                            column_config={"Borrar": st.column_config.CheckboxColumn(width="small"),
                                           "tag": st.column_config.TextColumn("Tag", width="medium"),
                                           "situacion": "Situación", "productos": "Productos", "activos": "Activos",
                                           "colecciones": st.column_config.TextColumn("Colecciones que lo usan",
                                                                                      width="large")})
        c1, c2 = st.columns([1, 2])
        # Excel: hoja resumen por tag (con sus modelo-color) + hoja detalle tag × modelo-color
        vv = V[["product_id", "sku", "stock"]].copy()
        vv["modelo_color"] = vv["sku"].map(lambda x: strip_size(x) if x else None).fillna("(sin SKU)")
        mc = (vv.groupby(["product_id", "modelo_color"])["stock"].sum().reset_index()
              .merge(P[["product_id", "titulo", "estado"]], on="product_id"))
        det = (ex[["product_id", "tags"]].rename(columns={"tags": "tag"}).merge(mc, on="product_id")
               .merge(T[["tag", "situacion", "colecciones"]], on="tag"))
        det["estado"] = det["estado"].map(lambda x: ESTADOS.get(x, x).split(" ", 1)[-1])
        det = det[["tag", "situacion", "colecciones", "modelo_color", "titulo", "estado", "stock"]].sort_values(
            ["tag", "modelo_color"]).rename(columns={"titulo": "producto"})
        res_x = T.merge(det.groupby("tag")["modelo_color"].apply(lambda s_: ", ".join(sorted(set(s_)))).rename(
            "modelos_color").reset_index(), on="tag", how="left")
        res_x["cant_modelos_color"] = res_x["modelos_color"].fillna("").map(lambda s_: len([x for x in s_.split(", ") if x]))
        res_x = res_x[["tag", "situacion", "colecciones", "productos", "activos", "cant_modelos_color", "modelos_color"]]

        def _xlsx_tags() -> bytes:
            import io
            buf = io.BytesIO()
            with pd.ExcelWriter(buf) as w:
                res_x.sort_values("productos").to_excel(w, sheet_name="Tags", index=False)
                det.to_excel(w, sheet_name="Detalle modelo-color", index=False)
            return buf.getvalue()
        c1.download_button("⬇️ Descargar Excel", _xlsx_tags(), f"{nombre}_tags.xlsx",
                           help="Hoja «Tags»: un tag por fila con sus modelo-color. Hoja «Detalle»: una fila por tag × modelo-color.")
        borrar = ed.loc[ed["Borrar"], "tag"].tolist()
        if borrar:
            en_col = [t for t in borrar if uso.get(t.strip().lower())]
            if en_col:
                st.warning("Estos tags **sí** los usa una colección automática; si los borrás, los productos salen de "
                           "esa colección: " + ", ".join(en_col))
            afect = P[P["tags"].apply(lambda ts: any(t in ts for t in borrar))]
            st.caption(f"Se quitan {len(borrar)} tag(s) de {len(afect)} producto(s): {', '.join(borrar[:20])}")
            with c2:
                if ejecutar_ui("🧹 Borrar tags seleccionados", len(afect), "lt",
                               f"Confirmo quitar {len(borrar)} tag(s) de {len(afect)} producto(s)"):
                    filas = [{"id": r["product_id"], "label": r["titulo"], "antes": list(r["tags"]),
                              "despues": [t for t in r["tags"] if t not in borrar]} for _, r in afect.iterrows()]
                    res = ops.aplicar(tienda, "tags_set", filas,
                                      f"{nombre}: limpiar {len(borrar)} tag(s) sin uso ({len(filas)} productos)",
                                      progress=progreso("Limpiando tags…"))
                    ops.mostrar_resultado(res)



# ================================================================ 2b. ver / descargar colecciones
@st.cache_data(ttl=600, show_spinner=False)
def _productos_coleccion(key: str, cid: str, nonce) -> list[str]:
    q = """query($id: ID!, $c: String) { collection(id: $id) { products(first: 250, after: $c) {
             pageInfo { hasNextPage endCursor } nodes { id } } } }"""
    cli, ids, cur = ShopifyClient(key), [], None
    while True:
        d = ((cli.gql(q, {"id": cid, "c": cur}, version=ops.COLL_VERSION).get("collection") or {}).get("products")) or {}
        ids += [n["id"] for n in d.get("nodes") or []]
        if not (d.get("pageInfo") or {}).get("hasNextPage"):
            return ids
        cur = d["pageInfo"]["endCursor"]


with t_col:
    nkc = f"coll_nonce_{tienda}"
    try:
        cols_all = _colecciones(tienda, st.session_state.get(nkc, 0))
    except ShopifyError as e:
        st.error(str(e))
        cols_all = pd.DataFrame(columns=["id", "titulo", "handle", "tipo", "productos"])
    cl = cols_all.set_index("id")
    elegidas = st.multiselect("Colecciones (escribí para buscar)", cols_all["id"].tolist(), key="vc_sel",
                              format_func=lambda i: f"{cl.loc[i, 'titulo']} · {cl.loc[i, 'tipo']} · "
                                                    f"{cl.loc[i, 'productos']} productos")
    c1, c2 = st.columns([1, 1])
    estados_vc = c1.multiselect("Estados", list(ESTADOS), default=["ACTIVE"], format_func=ESTADOS.get, key="vc_est")
    solo_stock_vc = c2.toggle("Solo con stock", value=False, key="vc_stock")
    if elegidas:
        filas = []
        info = P.set_index("product_id")
        for cid in elegidas:
            try:
                with st.spinner(f"Leyendo «{cl.loc[cid, 'titulo']}»…"):
                    pids = _productos_coleccion(tienda, cid, st.session_state.get(nkc, 0))
            except ShopifyError as e:
                st.error(str(e))
                continue
            vv = V[V["product_id"].isin(pids)].copy()
            vv["modelo_color"] = vv["sku"].map(lambda x: strip_size(x) if x else None)
            for (pid, mc), g in vv.groupby(["product_id", "modelo_color"], dropna=False):
                if pid not in info.index:
                    continue
                p = info.loc[pid]
                filas.append({
                    "coleccion": cl.loc[cid, "titulo"], "modelo_color": mc or "(sin SKU)", "producto": p["titulo"],
                    "estado": p["estado"], "tipo": p["tipo"], "talles": len(g),
                    "stock": int(g["stock"].fillna(0).sum()), "precio": g["precio"].max(),
                    "precio_tachado": g["precio_tachado"].max(), "foto": p["foto"], "url": p["url"] or "",
                })
        out = pd.DataFrame(filas, columns=["coleccion", "modelo_color", "producto", "estado", "tipo", "talles", "stock",
                                           "precio", "precio_tachado", "foto", "url"])
        if estados_vc:
            out = out[out["estado"].isin(estados_vc)]
        if solo_stock_vc:
            out = out[out["stock"] > 0]
        out = out.sort_values(["coleccion", "producto", "modelo_color"])
        m1, m2, m3 = st.columns(3)
        m1.metric("Modelo-color", out["modelo_color"].nunique())
        m2.metric("Productos", out["producto"].nunique())
        m3.metric("Stock total", f"{int(out['stock'].sum()):,}".replace(",", "."))
        st.dataframe(out.assign(estado=out["estado"].map(lambda x: ESTADOS.get(x, x))), hide_index=True, width="stretch",
                     row_height=50, height=min(40 + 52 * len(out), 520),
                     column_order=["foto", "coleccion", "modelo_color", "producto", "estado", "talles", "stock", "precio",
                                   "precio_tachado", "url"],
                     column_config={"foto": st.column_config.ImageColumn("", width="small"),
                                    "coleccion": "Colección", "modelo_color": "Modelo-color",
                                    "producto": st.column_config.TextColumn("Producto", width="large"),
                                    "precio": st.column_config.NumberColumn("Precio", format="$ %d"),
                                    "precio_tachado": st.column_config.NumberColumn("Tachado", format="$ %d"),
                                    "url": st.column_config.LinkColumn("Link", display_text="ver")})
        nombre_x = cl.loc[elegidas[0], "handle"] if len(elegidas) == 1 else "colecciones"
        st.download_button("⬇️ Descargar Excel", to_xlsx(out.drop(columns=["foto"]).assign(
            estado=out["estado"].map(lambda x: ESTADOS.get(x, x).split(" ", 1)[-1]))),
            f"{nombre}_{nombre_x}.xlsx", type="primary")



# ================================================================ ordenar productos de una colección
SORTS = {"MANUAL": "Manual", "BEST_SELLING": "Más vendidos", "ALPHA_ASC": "A-Z", "ALPHA_DESC": "Z-A",
         "PRICE_ASC": "Precio menor a mayor", "PRICE_DESC": "Precio mayor a menor", "CREATED": "Más viejos primero",
         "CREATED_DESC": "Más nuevos primero", "MANUAL_DESC": "Manual (invertido)"}


@st.cache_data(ttl=600, show_spinner=False)
def _orden_coleccion(key: str, cid: str, nonce) -> tuple[str, list[str]]:
    q = """query($id: ID!, $c: String) { collection(id: $id) { sortOrder
             products(first: 250, after: $c, sortKey: COLLECTION_DEFAULT) { pageInfo { hasNextPage endCursor } nodes { id } } } }"""
    cli, ids, cur, sort = ShopifyClient(key), [], None, ""
    while True:
        c = cli.gql(q, {"id": cid, "c": cur}, version=ops.COLL_VERSION).get("collection") or {}
        sort = c.get("sortOrder") or sort
        d = c.get("products") or {}
        ids += [n["id"] for n in d.get("nodes") or []]
        if not (d.get("pageInfo") or {}).get("hasNextPage"):
            return sort, ids
        cur = d["pageInfo"]["endCursor"]


with t_ord:
    st.caption("Elegí una colección, pegá tu listado de **modelo-color** y esos productos quedan **primeros, en el orden "
               "que pasaste**. El resto queda detrás. Se puede deshacer desde **Historial**.")
    nko = f"ord_nonce_{tienda}"
    try:
        cols_o = _colecciones(tienda, st.session_state.get(f"coll_nonce_{tienda}", 0))
    except ShopifyError as e:
        st.error(str(e))
        cols_o = pd.DataFrame(columns=["id", "titulo", "handle", "tipo", "productos"])
    clo = cols_o.set_index("id")
    cid = st.selectbox("Colección (escribí para buscar)", cols_o["id"].tolist(), index=None, key="ord_col",
                       placeholder="Ej.: Zapatillas, Hombre, Cyber…",
                       format_func=lambda i: f"{clo.loc[i, 'titulo']} · {clo.loc[i, 'tipo']} · {clo.loc[i, 'productos']} productos")
    sort_actual = None
    if cid:
        try:
            with st.spinner("Leyendo el orden actual de la colección…"):
                sort_actual, actual = _orden_coleccion(tienda, cid, st.session_state.get(nko, 0))
        except ShopifyError as e:
            st.error(str(e))
    if cid and sort_actual is not None:
        info = P.set_index("product_id")
        pos = {pid: i for i, pid in enumerate(actual)}
        en_col = P[P["product_id"].isin(pos)].copy()
        en_col["_pos"] = en_col["product_id"].map(pos)
        en_col = en_col.sort_values("_pos")
        st.caption(f"**{len(actual)}** productos · orden actual: **{SORTS.get(sort_actual, sort_actual)}**")
        if sort_actual != "MANUAL":
            st.info(f"La colección hoy se ordena por **{SORTS.get(sort_actual, sort_actual)}**. Para fijar tu orden "
                    "la paso a **Manual** (si deshacés, vuelve a como estaba).")

        c1, c2 = st.columns([1.4, 1])
        from meli.ui import caja_texto
        txt = caja_texto("Modelo-color en el orden que querés (uno por línea, se puede pegar desde Excel)", "ord_cod",
                         "✅ Armar orden", placeholder="P14313300000310SS25\nK134-KSA02\n…", container=c1)
        resto = c2.radio("¿Y el resto de la colección?", ["Mantener su orden actual", "Con stock primero, sin stock al final"],
                         key="ord_resto")
        c2.caption("Los productos de tu lista van siempre primero, aunque no tengan stock.")

        codigos = [x.strip() for x in txt.replace(";", "\n").splitlines() if x.strip()]
        primero, no_col, no_existe = [], [], []
        for c in codigos:
            hit, _ = _match_codigos(en_col, c)
            if hit.empty:
                (no_col if not _match_codigos(P, c)[0].empty else no_existe).append(c)
            for pid in hit.sort_values("_pos")["product_id"]:
                if pid not in primero:
                    primero.append(pid)
        if no_col:
            st.warning(f"{len(no_col)} existen en la tienda pero **no están en esta colección**: " + ", ".join(no_col[:30]))
        if no_existe:
            st.warning(f"No encontré {len(no_existe)}: " + ", ".join(no_existe[:30]))

        if primero or resto != "Mantener su orden actual":
            resto_ids = [pid for pid in actual if pid not in set(primero)]
            if resto != "Mantener su orden actual":
                stock = info["stock"].reindex(resto_ids).fillna(0)
                resto_ids = [p for p in resto_ids if stock.get(p, 0) > 0] + [p for p in resto_ids if not stock.get(p, 0) > 0]
            deseado = primero + resto_ids
            moves = ops.movimientos(actual, deseado)
            prev = pd.DataFrame({"product_id": deseado})
            prev["nueva"] = range(1, len(prev) + 1)
            prev["actual"] = prev["product_id"].map(pos).add(1)
            prev["foto"] = prev["product_id"].map(info["foto"]).fillna("")
            prev["producto"] = prev["product_id"].map(info["titulo"]).fillna(prev["product_id"])
            prev["skus"] = prev["product_id"].map(info["skus"]).fillna("")
            prev["stock"] = prev["product_id"].map(info["stock"])
            prev["origen"] = ["📌 Tu lista" if p in set(primero) else "" for p in prev["product_id"]]
            prev["cambio"] = (prev["actual"] - prev["nueva"]).map(lambda d: f"▲ {int(d)}" if d > 0 else f"▼ {int(-d)}" if d < 0 else "=")
            ver_todo = st.toggle("Ver la colección completa", value=False, key="ord_todo")
            vista = prev if ver_todo else prev.head(max(len(primero) + 10, 20))
            st.dataframe(vista, hide_index=True, width="stretch", row_height=50, height=min(40 + 52 * len(vista), 520),
                         column_order=["nueva", "foto", "producto", "skus", "stock", "actual", "cambio", "origen"],
                         column_config={"nueva": st.column_config.NumberColumn("#", width="small"),
                                        "foto": st.column_config.ImageColumn("", width="small"),
                                        "producto": st.column_config.TextColumn("Producto", width="large"),
                                        "actual": st.column_config.NumberColumn("Posición actual"),
                                        "cambio": "Cambio", "origen": ""})
            st.caption(f"**{len(primero)}** productos de tu lista arriba · **{len(moves)}** movimientos en Shopify")
            nom_col = clo.loc[cid, "titulo"]
            if ejecutar_ui("↕️ Aplicar orden", len(moves), "ord",
                           f"Confirmo reordenar «{nom_col}» ({len(primero)} primeros)"):
                with st.spinner("Reordenando en Shopify…"):
                    res = ops.aplicar(tienda, "coleccion_orden",
                                      [{"id": cid, "label": nom_col, "antes": actual, "despues": deseado}],
                                      f"{nombre}: ordenar «{nom_col}» ({len(primero)} primeros)",
                                      meta={"sort_antes": sort_actual}, progress=progreso("Moviendo productos…"))
                ops.mostrar_resultado(res)
                st.session_state[nko] = st.session_state.get(nko, 0) + 1
                _orden_coleccion.clear()
