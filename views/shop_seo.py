import pandas as pd
import streamlit as st

from meli import auditoria as au
from meli import contenido as ct
from meli import shop_ops as ops
from meli.config import secret
from meli.shop_ui import ESTADOS, cargar, colecciones, ejecutar_ui, pick_store, progreso, selector
from meli.shopify import ShopifyClient, ShopifyError, html_to_text, stores
from meli.theme import hero

hero("SEO y calidad Shopify", "Auditoría del catálogo, SEO masivo, texto alternativo de fotos y redirecciones 301.",
     "SHOPIFY · SEO")
tienda = pick_store()
nombre = stores()[tienda]["nombre"]
P, V, M, MF = cargar(tienda)
api_key = secret("ANTHROPIC_API_KEY")

t_aud, t_seo, t_alt, t_red = st.tabs(["🩺 Auditoría", "🔎 SEO masivo", "🖼️ Texto alternativo", "↪️ Redirecciones 301"])


def _seo_reglas(rows: pd.DataFrame) -> pd.DataFrame:
    out = rows[["product_id", "titulo", "seo_title", "seo_description", "descripcion_html"]].copy()
    sug = out.apply(lambda r: ct.seo_sugerido(r["titulo"], nombre, html_to_text(r["descripcion_html"])), axis=1)
    out["nuevo_title"] = [s[0] for s in sug]
    out["nuevo_meta"] = [s[1] for s in sug]
    return out


def _aplicar_seo(df: pd.DataFrame, desc: str):
    filas = [{"id": r["product_id"], "label": r["titulo"],
              "antes": {"title": r["seo_title"], "description": r["seo_description"]},
              "despues": {"title": r["nuevo_title"], "description": r["nuevo_meta"]}} for _, r in df.iterrows()]
    ops.mostrar_resultado(ops.aplicar(tienda, "seo", filas, desc, progress=progreso("SEO…")))


def _alt_reglas(prods: set | None = None) -> pd.DataFrame:
    m = M.merge(P[["product_id", "titulo"]], on="product_id")
    m["orden"] = m.groupby("product_id").cumcount()
    m["total"] = m.groupby("product_id")["media_id"].transform("count")
    m = m[m["alt"].fillna("").str.strip() == ""]
    if prods is not None:
        m = m[m["product_id"].isin(prods)]
    m["nuevo_alt"] = m.apply(lambda r: ct.alt_reglas(r["titulo"], r["orden"], r["total"]), axis=1)
    return m


def _aplicar_alt(df: pd.DataFrame, desc: str):
    filas = [{"id": r["media_id"], "label": r["titulo"], "antes": r["alt"] or "", "despues": r["nuevo_alt"]}
             for _, r in df.iterrows() if str(r["nuevo_alt"]).strip()]
    ops.mostrar_resultado(ops.aplicar(tienda, "alt", filas, desc, progress=progreso("Texto alternativo…")))


# ================================================================ 1. auditoría
with t_aud:
    A = au.auditar(P, V, M)
    score = au.puntaje(P, A)
    c0, c1, c2, c3 = st.columns(4)
    c0.metric("Salud del catálogo", f"{score}/100")
    c1.metric("🔴 Problemas graves", int((A["gravedad"] == "🔴 Alta").sum()))
    c2.metric("🟡 Medios", int((A["gravedad"] == "🟡 Media").sum()))
    c3.metric("Productos con algún problema", A["product_id"].nunique())
    solo_act = st.toggle("Solo productos activos / no listados", value=True, key="aud_act")
    if solo_act:
        A = A[A["estado"].isin(["ACTIVE", "UNLISTED"])]
    resumen = A.groupby(["check", "problema", "gravedad"]).size().reset_index(name="productos")
    resumen["_g"] = resumen["gravedad"].map({"🔴 Alta": 0, "🟡 Media": 1, "⚪ Baja": 2})
    resumen = resumen.sort_values(["_g", "productos"], ascending=[True, False]).reset_index(drop=True)
    if resumen.empty:
        st.success("Sin problemas detectados 🎉")
    else:
        st.dataframe(resumen[["gravedad", "problema", "productos"]], hide_index=True, width="stretch",
                     on_select="rerun", selection_mode="single-row", key="aud_tab",
                     column_config={"gravedad": st.column_config.TextColumn("", width="small"),
                                    "problema": st.column_config.TextColumn("Problema", width="large")})
        sel_rows = (st.session_state.get("aud_tab") or {}).get("selection", {}).get("rows", [])
        chk = resumen.iloc[sel_rows[0]]["check"] if sel_rows else st.selectbox(
            "Ver problema", resumen["check"], format_func=lambda k: au.CHECKS[k][0], key="aud_chk")
        det = A[A["check"] == chk]
        txt, grav, fix = au.CHECKS[chk]
        st.markdown(f"#### {grav.split()[0]} {txt} · {len(det)} productos")
        st.dataframe(det[["foto", "titulo", "estado", "detalle"]].assign(estado=det["estado"].map(ESTADOS)),
                     hide_index=True, width="stretch", row_height=50, height=min(40 + 52 * len(det), 380),
                     column_config={"foto": st.column_config.ImageColumn("", width="small"),
                                    "titulo": st.column_config.TextColumn("Producto", width="large")})
        cdl, cfix = st.columns([1, 2])
        cdl.download_button("⬇️ Descargar (CSV)", det[["titulo", "estado", "problema", "detalle", "product_id"]]
                            .to_csv(index=False).encode("utf-8-sig"), f"auditoria_{chk}_{tienda}.csv", "text/csv")
        pids = set(det["product_id"])
        if fix == "seo":
            with cfix:
                if ejecutar_ui("🔎 Completar SEO con reglas (gratis)", len(pids), "fix_seo",
                               f"Generar SEO title y meta para {len(pids)} producto(s) (solo los campos vacíos/largos)"):
                    df = _seo_reglas(P[P["product_id"].isin(pids)])
                    df["nuevo_title"] = df.apply(lambda r: r["seo_title"] if r["seo_title"] and len(r["seo_title"]) <= 70
                                                 else r["nuevo_title"], axis=1)
                    df["nuevo_meta"] = df.apply(lambda r: r["seo_description"] if r["seo_description"]
                                                and len(r["seo_description"]) <= 160 else r["nuevo_meta"], axis=1)
                    _aplicar_seo(df, f"{nombre}: SEO con reglas desde auditoría ({len(df)} productos)")
        elif fix == "alt":
            with cfix:
                if ejecutar_ui("🖼️ Completar alt con el título (gratis)", len(pids), "fix_alt"):
                    _aplicar_alt(_alt_reglas(pids), f"{nombre}: alt con reglas desde auditoría")
                st.caption("Para un alt que describa cada foto, usá la pestaña **Texto alternativo** con IA.")
        elif fix == "tachado":
            with cfix:
                if ejecutar_ui("🧹 Quitar tachados inválidos", len(pids), "fix_tach"):
                    bad = V[V["product_id"].isin(pids) & V["precio_tachado"].notna() & (V["precio_tachado"] <= V["precio"])]
                    filas = []
                    for pid, g in bad.groupby("product_id"):
                        filas.append({"id": pid, "label": P.set_index("product_id").loc[pid, "titulo"],
                                      "antes": [{"id": v["variant_id"], "compareAtPrice": f"{v['precio_tachado']:.2f}"}
                                                for _, v in g.iterrows()],
                                      "despues": [{"id": v["variant_id"], "compareAtPrice": None} for _, v in g.iterrows()]})
                    ops.mostrar_resultado(ops.aplicar(tienda, "precios", filas,
                                                      f"{nombre}: quitar tachados inválidos ({len(filas)} productos)",
                                                      progress=progreso("Precios…")))
        elif fix == "unlisted":
            with cfix:
                if ejecutar_ui("🔗 Pasar a No listado", len(pids), "fix_unl",
                               f"Ocultar {len(pids)} producto(s) sin stock (quedan accesibles por link directo)"):
                    rows = P[P["product_id"].isin(pids)]
                    filas = [{"id": r["product_id"], "label": r["titulo"], "antes": r["estado"], "despues": "UNLISTED"}
                             for _, r in rows.iterrows()]
                    ops.mostrar_resultado(ops.aplicar(tienda, "estado", filas,
                                                      f"{nombre}: {len(filas)} activos sin stock → No listado",
                                                      progress=progreso("Estados…")))
        elif fix == "fotos":
            try:
                cfix.page_link("views/shop_catalogo.py", label="Ir a Catálogo Shopify → Fotos (Azure)", icon="🖼️")
            except Exception:  # noqa: BLE001
                cfix.caption("Cargalas desde **Catálogo Shopify → Fotos (Azure)**.")

# ================================================================ 2. SEO masivo
with t_seo:
    st.caption("SEO title = título azul en Google (ideal ≤ 60) · Meta description = texto gris (ideal 120–155). "
               "No cambian el título ni la descripción que ve el cliente en la tienda.")
    solo_vacios = st.toggle("Solo productos sin SEO title o meta", value=True, key="seo_vac")
    base = P[(P["seo_title"] == "") | (P["seo_description"] == "")] if solo_vacios else P
    sel = selector(base, "seo", default_modo="Filtros")
    if not sel.empty:
        kg = f"seo_gen_{tienda}"
        c1, c2 = st.columns([1, 2])
        if c1.button("💡 Generar con reglas (gratis)", key="seo_gen", width="stretch"):
            st.session_state[kg] = _seo_reglas(sel)
        df = st.session_state.get(kg)
        if df is not None:
            df = df[df["product_id"].isin(sel["product_id"])]
            df = df.assign(c_t=df["nuevo_title"].str.len(), c_m=df["nuevo_meta"].str.len())
            ed = st.data_editor(df, hide_index=True, width="stretch", key=f"seo_ed_{len(df)}",
                                column_order=["titulo", "seo_title", "nuevo_title", "c_t", "nuevo_meta", "c_m"],
                                disabled=["titulo", "seo_title", "c_t", "c_m"],
                                column_config={"titulo": st.column_config.TextColumn("Producto", width="medium"),
                                               "seo_title": st.column_config.TextColumn("Title actual"),
                                               "nuevo_title": st.column_config.TextColumn("✏️ SEO title", width="medium",
                                                                                          max_chars=70),
                                               "c_t": st.column_config.NumberColumn("#", width="small"),
                                               "nuevo_meta": st.column_config.TextColumn("✏️ Meta description",
                                                                                         width="large", max_chars=160),
                                               "c_m": st.column_config.NumberColumn("#", width="small")})
            camb = ed[(ed["nuevo_title"] != ed["seo_title"]) | (ed["nuevo_meta"] != ed["seo_description"])]
            if ejecutar_ui("🔎 Guardar SEO", len(camb), "seo"):
                _aplicar_seo(camb, f"{nombre}: SEO masivo ({len(camb)} productos)")
                st.session_state.pop(kg, None)

# ================================================================ 3. texto alternativo
with t_alt:
    st.caption("El texto alternativo describe cada foto para Google Imágenes y lectores de pantalla.")
    todas = st.toggle("Incluir fotos que ya tienen alt", key="alt_todas")
    sel = selector(P, "alt", default_modo="Filtros")
    if not sel.empty:
        pids = set(sel["product_id"])
        m = M.merge(P[["product_id", "titulo"]], on="product_id")
        m["orden"] = m.groupby("product_id").cumcount()
        m["total"] = m.groupby("product_id")["media_id"].transform("count")
        m = m[m["product_id"].isin(pids)]
        if not todas:
            m = m[m["alt"].fillna("").str.strip() == ""]
        ka = f"alt_gen_{tienda}"
        modelo = secret("ANTHROPIC_MODEL_ALT", "claude-haiku-4-5")
        c1, c2, c3 = st.columns([1, 1, 2], vertical_alignment="center")
        if c1.button("💡 Con reglas (gratis)", key="alt_r", width="stretch", disabled=m.empty):
            st.session_state[ka] = {r["media_id"]: ct.alt_reglas(r["titulo"], r["orden"], r["total"]) for _, r in m.iterrows()}
        if c2.button("✨ Con IA (mira la foto)", key="alt_ia", width="stretch", disabled=m.empty or not api_key,
                     help=None if api_key else "Cargá ANTHROPIC_API_KEY en los Secrets."):
            from concurrent.futures import ThreadPoolExecutor, as_completed
            bar, gasto, gen = progreso("IA describiendo fotos…"), 0.0, {}
            with ThreadPoolExecutor(max_workers=4) as ex:
                futs = {ex.submit(ct.ai_alt, api_key, modelo, r["url"], r["titulo"]): r["media_id"] for _, r in m.iterrows()}
                for i, f in enumerate(as_completed(futs), 1):
                    try:
                        txt, c = f.result()
                        gen[futs[f]], gasto = txt, gasto + c
                    except Exception as e:  # noqa: BLE001
                        st.warning(str(e)[:200])
                    bar(i / len(futs))
            st.session_state[ka] = gen
            st.toast(f"Listo · US$ {gasto:.3f}")
        c3.caption(f"{len(m)} foto(s) · IA con {modelo}: ~US$ {len(m) * 0.002:.2f} aprox.")
        gen = st.session_state.get(ka, {})
        if m.empty:
            st.success("Todas las fotos de estos productos ya tienen texto alternativo ✅")
        else:
            m = m.assign(nuevo_alt=m["media_id"].map(gen).fillna(m["alt"].fillna("")).astype(str), alt=m["alt"].fillna("").astype(str))
            ed = st.data_editor(m[["url", "titulo", "alt", "nuevo_alt", "media_id"]], hide_index=True, width="stretch",
                                row_height=60, height=min(40 + 62 * len(m), 460), key=f"alt_ed_{len(m)}_{len(gen)}",
                                column_order=["url", "titulo", "alt", "nuevo_alt"], disabled=["url", "titulo", "alt"],
                                column_config={"url": st.column_config.ImageColumn("Foto", width="small"),
                                               "titulo": st.column_config.TextColumn("Producto", width="medium"),
                                               "alt": st.column_config.TextColumn("Alt actual"),
                                               "nuevo_alt": st.column_config.TextColumn("✏️ Alt nuevo", width="large",
                                                                                        max_chars=125)})
            camb = ed[ed["nuevo_alt"].fillna("") != ed["alt"].fillna("")].merge(m[["media_id"]], on="media_id")
            if ejecutar_ui("🖼️ Guardar texto alternativo", len(camb), "alt", f"Confirmo actualizar {len(camb)} foto(s)"):
                _aplicar_alt(camb, f"{nombre}: texto alternativo de {len(camb)} fotos")
                st.session_state.pop(ka, None)

# ================================================================ 4. redirecciones
with t_red:
    @st.cache_data(ttl=300, show_spinner=False)
    def _redirects(key: str, nonce: int) -> pd.DataFrame:
        q = """query($c: String) { urlRedirects(first: 250, after: $c) { pageInfo { hasNextPage endCursor }
                 nodes { id path target } } }"""
        cli, rows, cur = ShopifyClient(key), [], None
        while True:
            d = cli.gql(q, {"c": cur})["urlRedirects"]
            rows += d["nodes"]
            if not d["pageInfo"]["hasNextPage"] or len(rows) > 20000:
                break
            cur = d["pageInfo"]["endCursor"]
        return pd.DataFrame(rows, columns=["id", "path", "target"])

    nk = f"red_nonce_{tienda}"
    try:
        R = _redirects(tienda, st.session_state.get(nk, 0))
    except ShopifyError as e:
        st.error(str(e))
        R = pd.DataFrame(columns=["id", "path", "target"])
    st.caption(f"{len(R)} redirecciones existentes. Una 301 manda a quien entra a una URL vieja (de Google o un link "
               "guardado) a otra página, sin perder el posicionamiento.")
    modo_r = st.segmented_control("Crear", ["Productos archivados / borrador", "Pegar lista", "Ver / borrar existentes"],
                                  default="Productos archivados / borrador", key="red_modo") or "Pegar lista"
    nuevas = pd.DataFrame(columns=["path", "target", "label"])
    if modo_r == "Productos archivados / borrador":
        estados = st.multiselect("Estados", ["ARCHIVED", "DRAFT"], default=["ARCHIVED"], format_func=ESTADOS.get,
                                 key="red_est")
        cand = P[P["estado"].isin(estados)].copy()
        cand["path"] = "/products/" + cand["handle"]
        cand = cand[~cand["path"].isin(set(R["path"]))]
        try:
            cols = colecciones(tienda, 0)
        except ShopifyError:
            cols = pd.DataFrame(columns=["titulo", "handle"])

        def destino(r):
            t = str(r["tipo"] or "").lower()
            hit = cols[cols["titulo"].str.lower() == t] if t else cols.iloc[0:0]
            if hit.empty and t:
                hit = cols[cols["titulo"].str.lower().str.contains(t, regex=False)]
            return f"/collections/{hit.iloc[0]['handle']}" if not hit.empty else "/collections/all"
        cand["target"] = cand.apply(destino, axis=1) if not cand.empty else []
        st.caption(f"{len(cand)} producto(s) sin redirección. Destino sugerido: la colección de su tipo de producto "
                   "(o /collections/all). Editalo si querés mandarlos a otro lado.")
        if not cand.empty:
            cand.insert(0, "✔", True)
            ed = st.data_editor(cand[["✔", "foto", "titulo", "path", "target"]], hide_index=True, width="stretch",
                                key=f"red_ed_{len(cand)}", disabled=["foto", "titulo", "path"], row_height=48,
                                column_config={"foto": st.column_config.ImageColumn("", width="small"),
                                               "titulo": st.column_config.TextColumn("Producto", width="medium"),
                                               "path": "Desde", "target": st.column_config.TextColumn("✏️ Hacia", width="medium")})
            nuevas = ed[ed["✔"]].rename(columns={"titulo": "label"})[["path", "target", "label"]]
    elif modo_r == "Pegar lista":
        txt = st.text_area("Una por línea: origen ; destino  (o pegá dos columnas desde Excel)", key="red_txt", height=140,
                           placeholder="/products/zapatilla-vieja ; /products/zapatilla-nueva\n/collections/verano-2025 ; /collections/verano")
        rows = []
        for ln in txt.splitlines():
            parts = [x.strip() for x in ln.replace("\t", ";").split(";") if x.strip()]
            if len(parts) == 2:
                o, d = parts
                o = "/" + o.split("://", 1)[-1].split("/", 1)[-1] if "://" in o else (o if o.startswith("/") else "/" + o)
                rows.append({"path": o, "target": d, "label": o})
        nuevas = pd.DataFrame(rows, columns=["path", "target", "label"])
        if not nuevas.empty:
            ya = nuevas["path"].isin(set(R["path"]))
            if ya.any():
                st.warning(f"{int(ya.sum())} ya tienen redirección y se omiten: " + ", ".join(nuevas[ya]["path"][:10]))
            nuevas = nuevas[~ya]
            st.dataframe(nuevas[["path", "target"]], hide_index=True, width="stretch")
    else:
        q = st.text_input("Buscar", key="red_q")
        vr = R[R["path"].str.contains(q, case=False, regex=False) | R["target"].str.contains(q, case=False, regex=False)] if q else R
        vr = vr.copy()
        vr.insert(0, "Borrar", False)
        ed = st.data_editor(vr, hide_index=True, width="stretch", key=f"red_del_{len(vr)}",
                            disabled=["id", "path", "target"], column_order=["Borrar", "path", "target"])
        borrar = ed[ed["Borrar"]]
        if ejecutar_ui("🗑️ Borrar redirecciones", len(borrar), "red_del"):
            filas = [{"id": r["id"], "label": r["path"], "antes": {"path": r["path"], "target": r["target"]}, "despues": None}
                     for _, r in borrar.iterrows()]
            ops.mostrar_resultado(ops.aplicar(tienda, "redirect_remove", filas,
                                              f"{nombre}: borrar {len(filas)} redirecciones", progress=progreso("Borrando…")))
            st.session_state[nk] = st.session_state.get(nk, 0) + 1
    if modo_r != "Ver / borrar existentes" and not nuevas.empty:
        if ejecutar_ui("↪️ Crear redirecciones", len(nuevas), "red"):
            filas = [{"id": None, "label": r["label"], "antes": None, "despues": {"path": r["path"], "target": r["target"]}}
                     for _, r in nuevas.iterrows()]
            ops.mostrar_resultado(ops.aplicar(tienda, "redirect_add", filas, f"{nombre}: {len(filas)} redirecciones 301",
                                              progress=progreso("Creando…")))
            st.session_state[nk] = st.session_state.get(nk, 0) + 1
