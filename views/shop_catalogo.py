import json

import pandas as pd
import streamlit as st

from meli import azure_fotos as az
from meli import contenido as ct
from meli import shop_ops as ops
from meli.config import secret
from meli.shop_ui import ESTADOS, cargar, colecciones as _colecciones, ejecutar_ui, pick_store, progreso, \
    publicaciones as _publicaciones, selector
from meli.shopify import ShopifyClient, ShopifyError, html_to_text, stores
from meli.theme import hero

hero("Catálogo Shopify", "Estados, tags, colecciones, metacampos y fotos — en masa, con historial para deshacer.",
     "SHOPIFY · MASIVO")
tienda = pick_store()
nombre = stores()[tienda]["nombre"]
P, V, M, MF = cargar(tienda)
api_key = secret("ANTHROPIC_API_KEY")

t_est, t_tag, t_meta, t_fot = st.tabs(["🚦 Estados y canales", "🏷️ Tags y colecciones", "🧩 Metacampos", "🖼️ Fotos (Azure)"])


def _filas(sel: pd.DataFrame, antes_col, despues) -> list[dict]:
    return [{"id": r["product_id"], "label": r["titulo"],
             "antes": r[antes_col] if isinstance(antes_col, str) else antes_col(r),
             "despues": despues(r) if callable(despues) else despues} for _, r in sel.iterrows()]


# ================================================================ 1. estados y canales
with t_est:
    sel = selector(P, "est", extra_cols=["tags"])
    if not sel.empty:
        c1, c2 = st.columns([1, 1.4])
        nuevo = c1.selectbox("Nuevo estado", list(ESTADOS), format_func=ESTADOS.get, key="est_nuevo",
                             help="No listado: activo pero oculto de búsqueda, colecciones y recomendaciones; "
                                  "solo accesible por link directo.")
        pubs = _publicaciones(tienda)
        canales = c2.multiselect("Además publicar en canales (opcional)", [p["id"] for p in pubs],
                                 format_func=lambda i: next(p["nombre"] for p in pubs if p["id"] == i), key="est_pub",
                                 help="Ej. «pasar a activos y que estén en todos los canales».")
        if not pubs:
            c2.caption("Para publicar en canales la app necesita los permisos read/write_publications.")
        cambia = sel[sel["estado"] != nuevo]
        resumen = pd.DataFrame({"Antes": cambia["estado"].map(ESTADOS)}).value_counts().reset_index()
        st.caption(f"{len(cambia)} cambian de estado → {ESTADOS[nuevo]}"
                   + (f" · {len(sel)} se publican en {len(canales)} canal(es)" if canales else "")
                   + (" · " + ", ".join(f"{r['Antes']}: {r['count']}" for _, r in resumen.iterrows()) if len(resumen) else ""))
        if ejecutar_ui("🚦 Aplicar", len(cambia) + (len(sel) if canales else 0), "est"):
            if not cambia.empty:
                res = ops.aplicar(tienda, "estado", _filas(cambia, "estado", nuevo),
                                  f"{nombre}: {len(cambia)} productos → {ESTADOS[nuevo]}", progress=progreso("Estados…"))
                ops.mostrar_resultado(res)
            if canales:
                res = ops.aplicar(tienda, "publicar", _filas(sel, lambda r: None, canales),
                                  f"{nombre}: publicar {len(sel)} productos en {len(canales)} canal(es)",
                                  progress=progreso("Canales…"))
                ops.mostrar_resultado(res)

# ================================================================ 2. tags y colecciones
with t_tag:
    modo = st.segmented_control("¿Qué querés hacer?", ["Agregar tags", "Quitar tags", "Agregar a colección",
                                                        "Quitar de colección", "Crear colección"],
                                default="Agregar tags", key="tag_modo") or "Agregar tags"
    sel = selector(P, "tag", extra_cols=["tags"])
    tags_all = sorted({t for ts in P["tags"] for t in ts})
    if modo in ("Agregar tags", "Quitar tags"):
        if modo == "Agregar tags":
            c1, c2 = st.columns(2)
            exist = c1.multiselect("Tags existentes", tags_all, key="tag_ex")
            nuevos = c2.text_input("Tags nuevos (separados por coma)", key="tag_new")
            tags = list(dict.fromkeys(exist + [t.strip() for t in nuevos.split(",") if t.strip()]))
        else:
            en_sel = sorted({t for ts in sel["tags"] for t in ts}) if not sel.empty else tags_all
            tags = st.multiselect("Tags a quitar", en_sel, key="tag_rm")
        if tags and not sel.empty:
            if modo == "Agregar tags":
                afect = sel[sel["tags"].apply(lambda ts: any(t not in ts for t in tags))]
            else:
                afect = sel[sel["tags"].apply(lambda ts: any(t in ts for t in tags))]
            st.caption(f"{len(afect)} producto(s) cambian · tags: {', '.join(tags)}")
            if ejecutar_ui("🏷️ Aplicar tags", len(afect), "tag"):
                acc = "tags_add" if modo == "Agregar tags" else "tags_remove"
                res = ops.aplicar(tienda, acc, _filas(afect, "tags", tags),
                                  f"{nombre}: {modo.lower()} «{', '.join(tags)}» en {len(afect)} productos",
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

# ================================================================ 3. metacampos
with t_meta:
    @st.cache_data(ttl=600, show_spinner=False)
    def _defs(key: str) -> list[dict]:
        q = """{ metafieldDefinitions(ownerType: PRODUCT, first: 100) { nodes { name namespace key description
                 type { name } validations { name value } } } }"""
        return ShopifyClient(key).gql(q)["metafieldDefinitions"]["nodes"]

    try:
        defs = _defs(tienda)
    except ShopifyError as e:
        st.error(str(e))
        defs = []
    if not defs:
        st.info("Esta tienda no tiene definiciones de metacampos de producto (Configuración → Datos personalizados → Productos).")
    else:
        dk = st.selectbox("Metacampo", range(len(defs)), key="mf_def",
                          format_func=lambda i: f"{defs[i]['name']} · {defs[i]['namespace']}.{defs[i]['key']} "
                                                f"({defs[i]['type']['name']})")
        d = defs[dk]
        tipo = d["type"]["name"]
        opciones = []
        for v in d.get("validations") or []:
            if v["name"] == "choices":
                try:
                    opciones = json.loads(v["value"])
                except Exception:  # noqa: BLE001
                    pass
        if tipo.startswith("list.") or tipo in ("json", "rich_text_field") or "reference" in tipo:
            st.warning(f"El tipo «{tipo}» se carga como JSON: escribí el valor con el formato que espera Shopify "
                       "(ej. lista: [\"a\",\"b\"]).")
        sel = selector(P, "mf")
        if not sel.empty:
            mfd = MF[(MF["namespace"] == d["namespace"]) & (MF["key"] == d["key"])].set_index("product_id")["value"]
            base = sel[["product_id", "titulo"]].copy()
            base["actual"] = base["product_id"].map(mfd).fillna("")
            kv = f"mf_vals_{tienda}_{d['namespace']}.{d['key']}"
            vals = st.session_state.setdefault(kv, {})
            c1, c2, c3 = st.columns([1.5, 1, 1], vertical_alignment="bottom")
            if opciones:
                todos = c1.selectbox("Mismo valor para todos", [""] + opciones, key="mf_all")
            else:
                todos = c1.text_input("Mismo valor para todos", key="mf_all_t")
            if c2.button("⬇️ Poner en todos", key="mf_put", disabled=not todos, width="stretch"):
                for pid in base["product_id"]:
                    vals[pid] = todos
            if c3.button("✨ Completar con IA", key="mf_ia", disabled=not api_key, width="stretch",
                         help=None if api_key else "Cargá ANTHROPIC_API_KEY en los Secrets."):
                pend = base[base["actual"] == ""]
                bar, gasto = progreso("IA…"), 0.0
                info = P.set_index("product_id")
                for i in range(0, len(pend), 20):
                    lote = pend.iloc[i:i + 20]
                    prods = [{"titulo": info.loc[p, "titulo"], "tipo": info.loc[p, "tipo"], "tags": info.loc[p, "tags"],
                              "texto": html_to_text(info.loc[p, "descripcion_html"])} for p in lote["product_id"]]
                    try:
                        res_ia, c = ct.ai_metacampo(api_key, secret("ANTHROPIC_MODEL", "claude-sonnet-4-5"), prods,
                                                    d["name"], tipo, opciones)
                        gasto += c
                        for pid, v in zip(lote["product_id"], res_ia):
                            if v:
                                vals[pid] = v
                    except Exception as e:  # noqa: BLE001
                        st.error(str(e))
                        break
                    bar((i + 20) / max(len(pend), 1))
                st.toast(f"IA lista · US$ {gasto:.3f}")
            base["nuevo"] = base.apply(lambda r: vals.get(r["product_id"], r["actual"]), axis=1)
            colcfg = {"nuevo": (st.column_config.SelectboxColumn("✏️ Nuevo", options=[""] + opciones)
                                if opciones else st.column_config.TextColumn("✏️ Nuevo", width="large")),
                      "titulo": st.column_config.TextColumn("Producto", width="large"),
                      "actual": st.column_config.TextColumn("Actual")}
            ed = st.data_editor(base, hide_index=True, width="stretch", disabled=["product_id", "titulo", "actual"],
                                column_order=["titulo", "actual", "nuevo"], column_config=colcfg,
                                key=f"mf_ed_{kv}_{hash(tuple(sorted(vals.items())))}")
            for _, r in ed.iterrows():
                if r["nuevo"] != r["actual"]:
                    vals[r["product_id"]] = r["nuevo"]
            camb = ed[ed["nuevo"].fillna("") != ed["actual"].fillna("")]
            st.caption(f"{len(camb)} cambio(s). Dejar vacío un valor existente lo borra.")
            if ejecutar_ui("🧩 Guardar metacampos", len(camb), "mf"):
                filas = [{"id": r["product_id"], "label": r["titulo"], "antes": r["actual"] or None,
                          "despues": r["nuevo"] or None} for _, r in camb.iterrows()]
                res = ops.aplicar(tienda, "metacampos", filas, f"{nombre}: {d['name']} en {len(filas)} productos",
                                  {"namespace": d["namespace"], "key": d["key"], "type": tipo, "nombre": d["name"]},
                                  progress=progreso("Metacampos…"))
                ops.mostrar_resultado(res)
                st.session_state.pop(kv, None)

# ================================================================ 4. fotos desde Azure
with t_fot:
    st.caption(f"Fuente: `{az.base_url()}` · se matchea por código de artículo / modelo-color del SKU (y handle).")
    try:
        carps = az.carpetas()
    except Exception as e:  # noqa: BLE001
        st.error(f"No pude leer Azure: {e}")
        carps = []
    if carps:
        sug = next((c for c in carps if c.lower().replace(" ", "") == nombre.lower().replace(" ", "")), carps[0])
        c1, c2 = st.columns([1, 1.6])
        carpeta = c1.selectbox("Carpeta de Azure (marca)", carps, index=carps.index(sug), key="az_carp")
        modo_f = c2.radio("Modo", ["Solo productos sin fotos", "Agregar las que faltan", "Reemplazar todas"],
                          key="az_modo", horizontal=True,
                          help="Reemplazar: quita las fotos actuales y carga las de Azure (las quitadas no se pueden "
                               "restaurar con Deshacer).")
        with st.spinner("Listando fotos de Azure…"):
            F = az.fotos(carpeta)
        mt = az.matchear(P, F)
        sin_az = mt[mt["n_azure"] == 0]
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Productos", len(mt))
        m2.metric("Sin fotos en Shopify", int((mt["n_shopify"] == 0).sum()))
        m3.metric("Con fotos en Azure", int((mt["n_azure"] > 0).sum()))
        m4.metric("Sin fotos en Azure", len(sin_az))
        if modo_f == "Solo productos sin fotos":
            cand = mt[(mt["n_shopify"] == 0) & (mt["n_azure"] > 0)]
        elif modo_f == "Agregar las que faltan":
            cand = mt[mt["n_azure"] > mt["n_shopify"]]
        else:
            cand = mt[mt["n_azure"] > 0]
        cand = cand.copy()
        cand["estado"] = cand["estado"].map(lambda x: ESTADOS.get(x, x))
        cand["foto"] = cand["foto"].fillna("")
        cand.insert(0, "✔", True)
        cand["vista_azure"] = cand["urls"].map(lambda u: u[0] if u else None)
        ed = st.data_editor(cand[["✔", "vista_azure", "foto", "titulo", "estado", "n_shopify", "n_azure", "codigo_azure",
                                  "product_id"]], hide_index=True, width="stretch", row_height=56,
                            height=min(40 + 58 * len(cand), 460), key=f"az_ed_{carpeta}_{modo_f}_{len(cand)}",
                            disabled=["vista_azure", "foto", "titulo", "estado", "n_shopify", "n_azure", "codigo_azure"],
                            column_order=["✔", "vista_azure", "foto", "titulo", "estado", "n_shopify", "n_azure", "codigo_azure"],
                            column_config={"vista_azure": st.column_config.ImageColumn("Azure", width="small"),
                                           "foto": st.column_config.ImageColumn("Shopify", width="small"),
                                           "titulo": st.column_config.TextColumn("Producto", width="large"),
                                           "n_shopify": "Fotos Shopify", "n_azure": "Fotos Azure",
                                           "codigo_azure": "Código en Azure"})
        elegidos = cand[cand["product_id"].isin(ed.loc[ed["✔"], "product_id"])]
        cols_dl = st.columns(2)
        if not sin_az.empty:
            cols_dl[0].download_button("⬇️ Productos sin foto en Azure (CSV)",
                                       sin_az[["titulo", "skus", "estado"]].to_csv(index=False).encode("utf-8-sig"),
                                       f"sin_foto_azure_{tienda}.csv", "text/csv")
        if ejecutar_ui("🖼️ Cargar fotos", len(elegidos), "az"):
            mm = M.groupby("product_id")["media_id"].apply(list).to_dict()
            if modo_f == "Reemplazar todas":
                quitar = [{"id": r["product_id"], "label": r["titulo"], "antes": None, "despues": mm.get(r["product_id"], [])}
                          for _, r in elegidos.iterrows() if mm.get(r["product_id"])]
                if quitar:
                    ops.mostrar_resultado(ops.aplicar(tienda, "fotos_remove", quitar,
                                                      f"{nombre}: quitar fotos actuales de {len(quitar)} productos",
                                                      reversible=False, progress=progreso("Quitando fotos…")))
            filas = []
            urls_sh = M.groupby("product_id")["url"].apply(lambda s: {u.split("?")[0].rsplit("/", 1)[-1].lower() for u in s}).to_dict()
            for _, r in elegidos.iterrows():
                urls = r["urls"]
                if modo_f == "Agregar las que faltan":  # evita duplicar las que ya están (por nombre de archivo)
                    ya = urls_sh.get(r["product_id"], set())
                    urls = [u for u in urls if u.rsplit("/", 1)[-1].lower() not in ya]
                if urls:
                    filas.append({"id": r["product_id"], "label": r["titulo"], "alt": r["titulo"],
                                  "antes": [] if modo_f == "Reemplazar todas" else mm.get(r["product_id"], []),
                                  "despues": urls})
            res = ops.aplicar(tienda, "fotos_add", filas, f"{nombre}: cargar fotos de Azure/{carpeta} en {len(filas)} productos",
                              {"carpeta": carpeta}, progress=progreso("Cargando fotos…"))
            ops.mostrar_resultado(res)
            st.caption("Shopify descarga las imágenes en segundo plano: pueden tardar 1–2 minutos en aparecer.")
