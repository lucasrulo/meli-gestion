import html as html_mod
import io
from datetime import datetime

import pandas as pd
import streamlit as st

from meli.theme import hero

from meli import contenido as ct
from meli.api import MeliError
from meli.bulk import run_bulk
from meli.catalog import multiget
from meli.config import secret
from meli import shopify as sh
from meli.auth import get_token_manager
from meli.inconsistencias import strip_size
from meli.ui import catalog_index, pick_account, show_results

st.session_state["_page"] = "contenido"
hero("Contenido SEO / GEO", "Descripciones y ficha técnica optimizadas para el buscador de MeLi y los asistentes de IA.", "CATÁLOGO · IA")
client = pick_account()
index = catalog_index(client)
api_key = secret("ANTHROPIC_API_KEY")

# ---------------------------------------------------------------- publicaciones (agrupa variantes)
ix = index.drop_duplicates("item_id").copy()
for c in ("familia", "categoria"):
    if c not in ix:
        ix[c] = None
ix["pub"] = (ix["familia"].fillna("") + " · " + ix["categoria"].fillna("")).where(ix["familia"].notna(), ix["item_id"])
skus = index.groupby("item_id")["sku"].apply(lambda s: ", ".join(sorted({str(x) for x in s if x}))[:60])
ix["skus"] = ix["item_id"].map(skus)
pubs = (ix.groupby("pub")
        .agg(titulo=("titulo", "first"), familia=("familia", "first"), rep=("item_id", "first"),
             variantes=("item_id", "nunique"), item_ids=("item_id", lambda s: ",".join(s)),
             estado=("estado", "first"), skus=("skus", "first"), link=("permalink", "first"))
        .reset_index())
pubs["nombre"] = pubs["familia"].fillna(pubs["titulo"])

tab_an, tab_ed, tab_ia, tab_xl = st.tabs(["📊 Analizar catálogo", "✏️ Editar publicación", "✨ IA masiva",
                                          "📎 Excel ida y vuelta"])

def analizadas() -> pd.DataFrame | None:
    return st.session_state.get(f"cont_{client.user_id}")

# ---------------------------------------------------------------- 1. analizar
with tab_an:
    c1, c2 = st.columns([3, 1])
    q = c1.text_input("Filtrar por título o SKU (vacío = todo)", key="cont_q")
    est = c2.multiselect("Estados", ["active", "paused"], ["active"], key="cont_est")
    sel = pubs[pubs["estado"].isin(est)]
    if q:
        ql = q.lower()
        sel = sel[sel["nombre"].str.lower().str.contains(ql, regex=False, na=False)
                  | sel["skus"].fillna("").str.lower().str.contains(ql, regex=False)]
    st.write(f"**{len(sel)} publicaciones** ({int(sel['variantes'].sum())} variantes).")
    if st.button(f"📊 Analizar contenido de {len(sel)} publicaciones", type="primary"):
        bar = st.progress(0.0, text="Leyendo descripciones y fichas técnicas…")
        try:
            res = ct.analyze(client, sel["rep"].tolist(), progress=lambda p: bar.progress(p))
        except MeliError as e:
            st.error(str(e))
            st.stop()
        bar.empty()
        res = res.merge(sel[["rep", "pub", "nombre", "variantes", "item_ids", "skus", "link"]],
                        left_on="item_id", right_on="rep", how="left")
        prev = analizadas()
        if prev is not None:  # acumula análisis anteriores
            res = pd.concat([prev[~prev["pub"].isin(res["pub"])], res], ignore_index=True)
        st.session_state[f"cont_{client.user_id}"] = res

    df = analizadas()
    if df is not None and not df.empty:
        m = st.columns(4)
        m[0].metric("Analizadas", len(df))
        m[1].metric("Puntaje promedio", f"{df['score'].mean():.0f}/100")
        m[2].metric("Sin descripción", int((df["largo_desc"] == 0).sum()))
        m[3].metric("Con requeridos faltantes", int((df["faltan_requeridos"] != "").sum()))
        mx = st.slider("Mostrar con puntaje hasta", 0, 100, 100, 5, key="cont_mx")
        view = df[df["score"] <= mx].sort_values("score").reset_index(drop=True)
        if "foto" not in view:
            view["foto"] = None
        ev = st.dataframe(view[["foto", "score", "nombre", "variantes", "largo_desc", "ficha", "faltan_requeridos",
                                "mejoras", "skus", "link"]], hide_index=True, width="stretch", row_height=56,
                          on_select="rerun", selection_mode="single-row", key="cont_tabla",
                          column_config={"foto": st.column_config.ImageColumn("", width="small"),
                                         "score": st.column_config.ProgressColumn("Puntaje", min_value=0,
                                                                                  max_value=100, format="%d"),
                                         "nombre": st.column_config.TextColumn("Publicación", width="medium"),
                                         "largo_desc": st.column_config.NumberColumn("Caract."),
                                         "variantes": st.column_config.NumberColumn("Var."),
                                         "ficha": st.column_config.TextColumn("Ficha"),
                                         "faltan_requeridos": st.column_config.TextColumn("Requeridos faltantes"),
                                         "mejoras": st.column_config.TextColumn("Para mejorar", width="large"),
                                         "skus": st.column_config.TextColumn("SKUs"),
                                         "link": st.column_config.LinkColumn("Link", display_text="ver")})
        filas_sel = ev.selection.rows if ev and ev.selection else []
        if filas_sel:
            elegida = view.iloc[filas_sel[0]]["pub"]
            if st.session_state.get("_cont_last_sel") != elegida:
                st.session_state["_cont_last_sel"] = elegida
                st.session_state["cont_pid"] = elegida
            st.success(f"Seleccionada: **{view.iloc[filas_sel[0]]['nombre']}** → abrí la pestaña **✏️ Editar publicación**.")
        st.caption("Puntaje: largo y estructura de la descripción, palabras del título, ficha técnica y preguntas "
                   "frecuentes (GEO). Tocá una fila para abrirla en **Editar publicación**. Las fotos aparecen al volver a analizar.")

# ---------------------------------------------------------------- 2. editar una
def _foto(it: dict) -> str:
    pics = it.get("pictures") or []
    u = (pics[0].get("secure_url") or pics[0].get("url")) if pics else it.get("thumbnail")
    return (u or "").replace("http://", "https://")

def _chip(nombre: str, antes, despues, sufijo: str = "") -> str:
    d = (despues - antes) if isinstance(antes, (int, float)) else 0
    cls = "up" if d > 0 else ("down" if d < 0 else "")
    flecha = f' → <b class="{cls}">{despues}{sufijo}</b>' if d else ""
    return f'<span class="mo-chip">{nombre} <b>{antes}{sufijo}</b>{flecha}</span>'

with tab_ed:
    df = analizadas()
    if df is None or df.empty:
        st.info("Primero analizá el catálogo en la pestaña **📊 Analizar catálogo**.")
    else:
        opts = df.sort_values("score").reset_index(drop=True)
        plist = opts["pub"].tolist()
        lab = opts.set_index("pub")
        if st.session_state.get("cont_pid") not in plist:
            st.session_state["cont_pid"] = plist[0]

        def _mover(d: int) -> None:
            i = plist.index(st.session_state["cont_pid"])
            st.session_state["cont_pid"] = plist[(i + d) % len(plist)]

        # ---- selector: ◀ [buscar publicación] ▶
        n1, n2, n3, n4 = st.columns([0.07, 1, 0.07, 0.2], vertical_alignment="center")
        n1.button("◀", key="cont_prev", on_click=_mover, args=(-1,), help="Anterior", width="stretch")
        pid = n2.selectbox("Publicación", plist, key="cont_pid", label_visibility="collapsed",
                           format_func=lambda p: f"{int(lab.loc[p, 'score'])} pts · {lab.loc[p, 'nombre']}")
        n3.button("▶", key="cont_next", on_click=_mover, args=(1,), help="Siguiente", width="stretch")
        n4.caption(f"{plist.index(pid) + 1} / {len(plist)}", help="Ordenadas de peor a mejor puntaje")

        row = lab.loc[pid]
        rep = row["item_id"]
        desc_act = row["descripcion"] or ""
        item = {it["id"]: it for it in multiget(client, [rep])}.get(rep, {})
        cat = ct.category_attributes(client, item.get("category_id")) if item else []
        vals = ct.item_attr_values(item)
        titulo = item.get("title", row["nombre"])

        # ---- Shopify: producto equivalente (por SKU)
        prod, sel_p, scli, opciones, tiendas = None, None, None, [], []
        stores = sh.stores()
        if stores:
            alias = get_token_manager().accounts().get(client.user_id, {}).get("alias")
            tiendas = sh.stores_for_meli(alias)
            variants = sh.variants_for(tiendas)
            skus_pub = set(index[index["item_id"].isin(row["item_ids"].split(","))]["sku"].dropna().astype(str))
            mcs = {strip_size(x) for x in skus_pub}
            hit = variants[variants["sku"].notna() & (variants["sku"].str.upper().isin({x.upper() for x in skus_pub})
                                                      | variants["sku"].map(strip_size).isin(mcs))]
            opciones = hit.drop_duplicates("product_id").to_dict("records")
            if opciones:
                pi = min(st.session_state.get(f"cont_sp_{rep}", 0), len(opciones) - 1)
                sel_p = opciones[pi]
                kprod = f"cont_shopprod_{sel_p['product_id']}"
                scli = sh.ShopifyClient(sel_p["tienda"])
                if kprod not in st.session_state:
                    try:
                        st.session_state[kprod] = (scli.products([sel_p["product_id"]]) or [{}])[0]
                    except sh.ShopifyError as e:
                        st.error(str(e))
                        st.session_state[kprod] = {}
                prod = st.session_state[kprod] or None

        # ---- estado editable (se inicializa con lo actual)
        k_new = f"cont_new_{rep}"
        st.session_state.setdefault(k_new, desc_act)
        seo = (prod or {}).get("seo") or {}
        html_act = (prod or {}).get("descriptionHtml") or ""
        kh, kt, kd = f"cont_sh_html_{rep}", f"cont_sh_t_{rep}", f"cont_sh_d_{rep}"
        if st.session_state.pop(f"cont_shreload_{rep}", False):
            for k in (kh, kt, kd):
                st.session_state.pop(k, None)
        if prod:
            st.session_state.setdefault(kh, html_act)
            st.session_state.setdefault(kt, seo.get("title") or "")
            st.session_state.setdefault(kd, seo.get("description") or "")

        card_ph = st.container(border=True)  # se completa al final (puntajes en vivo)

        # ---- barra de acciones: IA + descartar
        a1, a2, a3 = st.columns([1, 1, 3], vertical_alignment="center")
        with a1.popover("✨ Mejorar con IA", width="stretch", disabled=not api_key,
                        help=None if api_key else "Cargá ANTHROPIC_API_KEY en los Secrets."):
            extra = st.text_input("Indicaciones (opcional)", key=f"cont_extra_{rep}",
                                  placeholder="Ej: destacar que es para césped natural")
            ia_m = st.checkbox("MeLi: descripción + ficha técnica", value=True, key=f"cont_iam_{rep}")
            ia_s = st.checkbox("Shopify: HTML + SEO", value=bool(prod), disabled=not prod, key=f"cont_ias_{rep}")
            if st.button("Generar", type="primary", key=f"cont_ai_{rep}", width="stretch", disabled=not (ia_m or ia_s)):
                modelo = secret("ANTHROPIC_MODEL", "claude-sonnet-4-5")
                try:
                    with st.spinner("Generando con Claude…"):
                        gasto = 0.0
                        if ia_m:
                            sug, c = ct.ai_suggest(api_key, modelo, item, desc_act, cat, extra)
                            st.session_state[k_new] = sug.get("descripcion", "")
                            st.session_state[f"cont_attrsug_{rep}"] = {a["id"]: a.get("valor") for a in sug.get("atributos", [])
                                                                       if a.get("id") and a.get("valor")}
                            gasto += c
                        if ia_s and prod:
                            attrs = {a.get("name") or a.get("id"): a.get("value_name")
                                     for a in (item.get("attributes") or []) if a.get("value_name")}
                            d, c = ct.ai_suggest_shopify(api_key, modelo, prod.get("title"),
                                                         ct.limpiar(st.session_state[k_new]) or desc_act, attrs, extra)
                            st.session_state[kh] = d.get("html", "")
                            st.session_state[kt] = d.get("seo_title", "")[:70]
                            st.session_state[kd] = d.get("seo_description", "")[:160]
                            gasto += c
                    st.session_state["cont_gasto"] = st.session_state.get("cont_gasto", 0) + gasto
                    st.toast(f"Listo · costo aprox. US$ {gasto:.3f}")
                    st.rerun()
                except Exception as e:  # noqa: BLE001
                    st.error(str(e))
        if a2.button("↩️ Descartar cambios", key=f"cont_reset_{rep}", width="stretch"):
            st.session_state[k_new] = desc_act
            st.session_state.pop(f"cont_attrsug_{rep}", None)
            if prod:
                st.session_state[kh], st.session_state[kt], st.session_state[kd] = (
                    html_act, seo.get("title") or "", seo.get("description") or "")
            st.rerun()
        if st.session_state.get("cont_gasto"):
            a3.caption(f"Gasto de IA en esta sesión: US$ {st.session_state['cont_gasto']:.3f}")

        # ---- pestañas por canal
        vacios = sum(1 for a in cat if not vals.get(a["id"]))
        t_m, t_f, t_s = st.tabs(["📝 Descripción MeLi", f"🧾 Ficha técnica · {vacios} vacíos",
                                 "🛍️ Shopify" if prod else "🛍️ Shopify (sin producto)"])
        with t_m:
            comparar_m = st.toggle("Comparar con la actual", key=f"cont_cmpm_{rep}")
            if comparar_m:
                c1, c2 = st.columns(2)
                c1.text_area("Actual", desc_act or "(sin descripción)", height=260, disabled=True)
                box = c2
            else:
                box = st
            nueva = box.text_area("Descripción nueva", height=260, key=k_new, label_visibility="collapsed"
                                  if not comparar_m else "visible")
            limpia = ct.limpiar(nueva)
            aviso = " · ⚠️ tiene HTML/links/emojis: se limpia al guardar" if limpia != nueva.strip() else ""
            st.caption(f"{len(nueva)} caracteres · texto plano{aviso} · Ctrl+Enter aplica lo que escribiste")

        with t_f:
            sug = st.session_state.get(f"cont_attrsug_{rep}", {})
            at = pd.DataFrame([{
                "id": a["id"], "atributo": a["nombre"] + (" *" if a["requerido"] else ""),
                "valor_actual": vals.get(a["id"], ""), "valor_nuevo": sug.get(a["id"], vals.get(a["id"], "")),
                "valores_posibles": ", ".join(a["valores"][:12]),
            } for a in cat])
            if at.empty:
                st.caption("No se pudo leer la ficha técnica de esta categoría.")
                at_ed = at
            else:
                solo_falt = st.toggle("Solo los vacíos", value=True, key=f"cont_sf_{rep}")
                show_at = at[at["valor_actual"] == ""] if solo_falt else at
                at_ed = st.data_editor(show_at, hide_index=True, width="stretch", key=f"cont_at_{rep}_{len(sug)}",
                                       height=min(38 + 35 * max(len(show_at), 1), 320),
                                       disabled=["id", "atributo", "valor_actual", "valores_posibles"],
                                       column_order=["atributo", "valor_actual", "valor_nuevo", "valores_posibles"],
                                       column_config={"atributo": st.column_config.TextColumn("Atributo"),
                                                      "valor_actual": st.column_config.TextColumn("Actual"),
                                                      "valor_nuevo": st.column_config.TextColumn("✏️ Nuevo"),
                                                      "valores_posibles": st.column_config.TextColumn(
                                                          "Valores posibles", width="large")})
                st.caption("* requerido · si hay valores posibles, escribí uno de esos exactamente.")
        cambios_attr = {r["id"]: r["valor_nuevo"] for _, r in at_ed.iterrows()
                        if str(r["valor_nuevo"] or "").strip() and r["valor_nuevo"] != r["valor_actual"]} \
            if not at_ed.empty else {}

        shop_cambios, sa, sb, sb_n = {}, None, None, []
        with t_s:
            if not stores:
                st.caption("No hay tiendas Shopify conectadas (ver **Cuentas**).")
            elif not prod:
                st.caption("No encontré este artículo en Shopify (por SKU) en: "
                           + ", ".join(stores[t]["nombre"] for t in tiendas))
            else:
                if len(opciones) > 1:
                    st.selectbox("Producto Shopify", range(len(opciones)), key=f"cont_sp_{rep}",
                                 format_func=lambda i: f"{opciones[i]['producto']} · {opciones[i]['tienda_nombre']} · "
                                                       f"{opciones[i]['estado']}")
                s1, s2, s3 = st.columns([1.2, 1, 1.4], vertical_alignment="center")
                if s1.button("↳ Copiar la descripción de MeLi", key=f"cont_conv_{rep}", width="stretch"):
                    st.session_state[kh] = sh.text_to_html(limpia)
                    st.rerun()
                comparar_s = s2.toggle("Comparar con la actual", key=f"cont_cmps_{rep}")
                prev_s = s3.toggle("Vista previa", key=f"cont_prevs_{rep}")
                if comparar_s:
                    h1, h2 = st.columns(2)
                    h1.text_area("Actual (HTML)", html_act or "(vacía)", height=240, disabled=True)
                    html_new = h2.text_area("Nueva (HTML)", height=240, key=kh)
                else:
                    html_new = st.text_area("Descripción (HTML)", height=240, key=kh, label_visibility="collapsed")
                if prev_s:
                    with st.container(border=True):
                        st.markdown(html_new, unsafe_allow_html=True)
                # ---- SEO: lo que muestra Google (Shopify → producto → "Optimización para motores de búsqueda")
                r1, r2 = st.columns([3, 1.2], vertical_alignment="center")
                r1.markdown("**🔎 Cómo aparece en Google**  \n"
                            "<span style='color:var(--muted);font-size:.8rem'>Se guarda en Shopify → producto → "
                            "<i>Optimización para motores de búsqueda</i> (título de la página y meta descripción). "
                            "Si lo dejás vacío, Google usa el título y el comienzo de la descripción.</span>",
                            unsafe_allow_html=True)
                if r2.button("💡 Sugerir (sin IA)", key=f"cont_seosug_{rep}", width="stretch",
                             help="Arma título y meta description con reglas, gratis. Después lo podés editar."):
                    st.session_state[kt], st.session_state[kd] = ct.seo_sugerido(
                        prod.get("title"), stores[sel_p["tienda"]]["nombre"],
                        sh.html_to_text(html_new) or limpia, titulo)
                q1, q2 = st.columns([1, 1.6])
                seo_t = q1.text_input("SEO title (ideal ≤ 60)", key=kt, max_chars=70)
                seo_d = q2.text_input("Meta description (ideal 120–155)", key=kd, max_chars=160)
                g_t = seo_t or prod.get("title") or ""
                g_d = seo_d or ct._cortar(sh.html_to_text(html_new), 155)
                g_u = prod.get("onlineStoreUrl") or f"{stores[sel_p['tienda']]['shop']}/products/{prod.get('handle', '')}"
                g_t, g_d = html_mod.escape(g_t), html_mod.escape(g_d)
                st.markdown(
                    f"<div style='background:#fff;border-radius:12px;padding:12px 16px;font-family:Arial,sans-serif;"
                    f"max-width:640px'><div style='color:#202124;font-size:12px'>{g_u}</div>"
                    f"<div style='color:#1a0dab;font-size:18px;line-height:1.3;margin:2px 0'>{g_t[:60]}"
                    f"{'…' if len(g_t) > 60 else ''}</div>"
                    f"<div style='color:#4d5156;font-size:13px;line-height:1.45'>{g_d[:155]}"
                    f"{'…' if len(g_d) > 155 else ''}</div></div>", unsafe_allow_html=True)
                sa, _ = ct.shop_score(prod.get("title"), html_act, seo.get("title") or "", seo.get("description") or "")
                sb, sb_n = ct.shop_score(prod.get("title"), html_new, seo_t, seo_d)
                if html_new.strip() != html_act.strip():
                    shop_cambios["description_html"] = html_new
                if seo_t != (seo.get("title") or ""):
                    shop_cambios["seo_title"] = seo_t
                if seo_d != (seo.get("description") or ""):
                    shop_cambios["seo_description"] = seo_d

        # ---- tarjeta del producto (foto + puntajes en vivo)
        cambia_desc = limpia != desc_act.strip()
        filled_act = sum(1 for a in cat if vals.get(a["id"]))
        filled_new = sum(1 for a in cat if vals.get(a["id"]) or cambios_attr.get(a["id"]))
        cmp_ = ct.comparar(titulo, desc_act, limpia, filled_act, filled_new, len(cat))
        foto = _foto(item) or ((((prod or {}).get("featuredMedia") or {}).get("preview") or {}).get("image") or {}).get("url", "")
        mlink = row["link"] if isinstance(row["link"], str) and row["link"] else item.get("permalink")
        links = [f'<a href="{mlink}" target="_blank">MeLi ↗</a>'] if mlink else []
        if prod and prod.get("onlineStoreUrl"):
            links.append(f'<a href="{prod["onlineStoreUrl"]}" target="_blank">Shopify ↗</a>')
        chips = _chip("MeLi", cmp_["antes"], cmp_["despues"]) + _chip("Ficha", filled_act, filled_new, f"/{len(cat)}")
        if prod:
            chips += _chip("Shopify", sa, sb)
        pend = cmp_["pendientes"] + [f"Shopify: {x}" for x in sb_n]
        skus_txt = str(row.get("skus") or "")
        img_html = f'<img src="{foto}"/>' if foto else '<div class="noimg">sin foto</div>'
        pend_txt = ("Pendiente: " + " · ".join(pend[:6])) if pend else "✅ Contenido completo"
        links_txt = " · ".join(links)
        with card_ph:
            st.markdown(
                f'<div class="mo-prod">{img_html}'
                f'<div class="info"><div class="t">{titulo}</div>'
                f'<div class="meta">{int(row["variantes"])} variante(s) · {skus_txt} · {links_txt}</div>'
                f'<div class="chips">{chips}</div>'
                f'<div class="pend">{pend_txt}</div>'
                f'</div></div>', unsafe_allow_html=True)

        # ---- guardar
        ids = row["item_ids"].split(",")
        with st.container(border=True):
            g1, g2, g3, g4 = st.columns([1, 1, 1.2, 1.3], vertical_alignment="center")
            hay_m = bool(cambia_desc or cambios_attr)
            en_meli = g1.toggle("MeLi", value=hay_m, disabled=not hay_m, key=f"cont_gm_{rep}_{hay_m}")
            en_shop = g2.toggle("Shopify", value=bool(shop_cambios), disabled=not shop_cambios,
                                key=f"cont_gs_{rep}_{bool(shop_cambios)}")
            todas = g3.toggle(f"Las {len(ids)} variantes", value=True, key=f"cont_all_{rep}",
                              help="Aplica la descripción/ficha de MeLi a todas las variantes de la publicación.")
            destino = ids if todas else [rep]
            guardar = g4.button("💾 Guardar", type="primary", disabled=not (en_meli or en_shop),
                                key=f"cont_save_{rep}", width="stretch")
            resumen = []
            if en_meli:
                partes = (["descripción"] if cambia_desc else []) + ([f"{len(cambios_attr)} atributos"] if cambios_attr else [])
                resumen.append(f"MeLi: {' + '.join(partes)} → {len(destino)} publicación(es)")
            if en_shop:
                resumen.append("Shopify: " + ", ".join({"description_html": "descripción", "seo_title": "SEO title",
                                                         "seo_description": "meta description"}[k] for k in shop_cambios))
            st.caption(" · ".join(resumen) if resumen else "Sin cambios para guardar todavía.")
        if guardar:
            filas = [{"canal": "MeLi", "id": i} for i in destino] if en_meli else []
            if en_shop:
                filas.append({"canal": "Shopify", "id": prod.get("id")})

            def job(r):
                if r["canal"] == "MeLi":
                    if cambia_desc:
                        ct.set_description(client, r["id"], limpia)
                    if cambios_attr:
                        ct.set_attributes(client, r["id"], cambios_attr)
                else:
                    scli.update_product_content(r["id"], **shop_cambios)

            res = run_bulk(filas, job, label="Guardando")
            show_results(res, f"resultado_contenido_{datetime.now():%Y%m%d_%H%M}.xlsx")
            okm = res[(res["canal"] == "MeLi") & (res["resultado"] == "OK")]
            from meli import historial
            if en_meli and cambia_desc and not okm.empty:
                historial.registrar("MeLi", get_token_manager().accounts().get(client.user_id, {}).get("alias") or client.user_id,
                                    "meli_descripcion", f"Descripción MeLi: {titulo}",
                                    [{"id": i, "label": titulo, "antes": desc_act, "despues": limpia, "ok": True, "error": ""}
                                     for i in okm["id"]], {"user_id": client.user_id})
            if en_shop and (res[res["canal"] == "Shopify"]["resultado"] == "OK").all():
                ant = {"descriptionHtml": html_act, "seo": {"title": seo.get("title") or "",
                                                           "description": seo.get("description") or ""}}
                nue = {"descriptionHtml": shop_cambios.get("description_html", html_act),
                       "seo": {"title": shop_cambios.get("seo_title", ant["seo"]["title"]),
                               "description": shop_cambios.get("seo_description", ant["seo"]["description"])}}
                historial.registrar("Shopify", sel_p["tienda"], "contenido", f"Contenido Shopify: {prod.get('title')}",
                                    [{"id": prod.get("id"), "label": prod.get("title"), "antes": ant, "despues": nue,
                                      "ok": True, "error": ""}])
            if en_meli and len(okm) == len(destino):
                df.loc[df["pub"] == pid, "descripcion"] = limpia
                df.loc[df["pub"] == pid, "largo_desc"] = len(limpia)
                df.loc[df["pub"] == pid, "score"] = cmp_["despues"]
                df.loc[df["pub"] == pid, "mejoras"] = " · ".join(cmp_["pendientes"])
            if en_shop and (res[res["canal"] == "Shopify"]["resultado"] == "OK").all():
                st.session_state.pop(f"cont_shopprod_{prod.get('id')}", None)
                st.session_state[f"cont_shreload_{rep}"] = True  # releer de Shopify en la próxima corrida

# ---------------------------------------------------------------- 3. IA masiva
with tab_ia:
    df = analizadas()
    model = secret("ANTHROPIC_MODEL", "claude-sonnet-4-5")
    if not api_key:
        st.info("Para usar la IA cargá **ANTHROPIC_API_KEY** en los secrets de Streamlit (ver instrucciones en el README). "
                "Mientras tanto podés editar a mano o por Excel.")
    elif df is None or df.empty:
        st.info("Primero analizá el catálogo en **📊 Analizar catálogo**.")
    else:
        c1, c2 = st.columns(2)
        n = c1.number_input("Cuántas publicaciones (las de peor puntaje)", 1, max(1, len(df)), min(10, len(df)))
        extra_m = c2.text_input("Indicaciones para todas (opcional)", key="cont_extra_m")
        lote = df.sort_values("score").head(int(n))
        st.caption(f"Modelo: `{model}` · costo estimado ≈ US$ {ct.estimar_costo(len(lote), model):.2f} "
                   f"({len(lote)} publicaciones; cada una se aplica a todas sus variantes).")
        if st.button(f"✨ Generar {len(lote)} propuestas", type="primary"):
            cola, gasto = [], 0.0
            items = {it["id"]: it for it in multiget(client, lote["item_id"].tolist())}
            bar = st.progress(0.0)
            for k, (_, r) in enumerate(lote.iterrows(), 1):
                it = items.get(r["item_id"])
                if not it:
                    continue
                try:
                    sug, c = ct.ai_suggest(api_key, model, it, r["descripcion"],
                                           ct.category_attributes(client, it.get("category_id")), extra_m)
                    gasto += c
                    cola.append({"pub": r["pub"], "nombre": r["nombre"], "item_ids": r["item_ids"],
                                 "titulo": it.get("title"), "ficha": r["ficha"],
                                 "actual": r["descripcion"], "nueva": sug.get("descripcion", ""),
                                 "atributos": {a["id"]: a["valor"] for a in sug.get("atributos", [])
                                               if a.get("id") and a.get("valor")}})
                except Exception as e:  # noqa: BLE001
                    st.warning(f"{r['nombre']}: {e}")
                bar.progress(k / len(lote), text=f"{k}/{len(lote)} · US$ {gasto:.3f}")
            bar.empty()
            st.session_state["cont_cola"] = cola
            st.session_state["cont_gasto"] = st.session_state.get("cont_gasto", 0) + gasto

        cola = st.session_state.get("cont_cola", [])
        if cola:
            st.subheader(f"Revisión · {len(cola)} propuestas")
            for i, p in enumerate(cola):
                _fa, _tot = ct.parse_ficha(p.get("ficha", ""))
                _c = ct.comparar(p.get("titulo") or p["nombre"], p["actual"], ct.limpiar(p["nueva"]), _fa,
                                 min(_tot, _fa + len(p["atributos"])), _tot)
                with st.expander(f"{p['nombre']} · {len(p['item_ids'].split(','))} variante(s) · "
                                 f"puntaje {_c['antes']} → {_c['despues']}", expanded=i < 2):
                    a, b = st.columns(2)
                    a.text_area("Actual", p["actual"], height=300, disabled=True, key=f"q_cur_{i}")
                    p["nueva"] = b.text_area("Propuesta (editable)", p["nueva"], height=300, key=f"q_new_{i}")
                    fa, tot = ct.parse_ficha(p.get("ficha", ""))
                    fn = min(tot, fa + len(p["atributos"]))
                    cp = ct.comparar(p.get("titulo") or p["nombre"], p["actual"], ct.limpiar(p["nueva"]), fa, fn, tot)
                    a.metric("Puntaje actual", f"{cp['antes']}/100")
                    b.metric("Puntaje propuesta", f"{cp['despues']}/100", delta=cp["delta"])
                    if cp["pendientes"]:
                        b.caption("Pendiente: " + " · ".join(cp["pendientes"]))
                    if p["atributos"]:
                        st.caption("Atributos propuestos: " + " · ".join(f"{k}: {v}" for k, v in p["atributos"].items()))
                        p["usar_attrs"] = st.checkbox("Aplicar también estos atributos", value=True, key=f"q_at_{i}")
                    p["aprobar"] = st.checkbox("✅ Aprobar", value=False, key=f"q_ok_{i}")
            aprob = [p for p in cola if p.get("aprobar")]
            if st.button(f"💾 Aplicar {len(aprob)} aprobadas", type="primary", disabled=not aprob):
                filas = [{"publicacion": p["nombre"], "item_id": iid, "desc": ct.limpiar(p["nueva"]),
                          "attrs": p["atributos"] if p.get("usar_attrs") else {}}
                         for p in aprob for iid in p["item_ids"].split(",")]

                def job(r):
                    ct.set_description(client, r["item_id"], r["desc"])
                    if r["attrs"]:
                        ct.set_attributes(client, r["item_id"], r["attrs"])

                res = run_bulk(filas, job, label="Guardando")
                show_results(res[["publicacion", "item_id", "resultado", "error", "procesado"]],
                             f"resultado_ia_{datetime.now():%Y%m%d_%H%M}.xlsx")
        if st.session_state.get("cont_gasto"):
            st.caption(f"Gasto de IA en esta sesión: US$ {st.session_state['cont_gasto']:.3f}")

# ---------------------------------------------------------------- 4. Excel ida y vuelta (por modelo-color, MeLi ↔ Shopify)
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
        st.warning("No hay una tienda Shopify asociada a esta cuenta de MeLi (ver **Cuentas**).")

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
        st.info("Para traer las descripciones de MeLi primero analizá el catálogo en **📊 Analizar catálogo** "
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
