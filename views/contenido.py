import io
from datetime import datetime

import pandas as pd
import streamlit as st

from meli import contenido as ct
from meli.api import MeliError
from meli.bulk import run_bulk
from meli.catalog import multiget
from meli.config import secret
from meli.ui import catalog_index, pick_account, show_results

st.session_state["_page"] = "contenido"
st.title("📝 Contenido SEO / GEO")
st.caption("Descripciones y ficha técnica de tus publicaciones: puntaje, edición tipo cajas de texto, sugerencias con IA "
           "(opcional) y aplicación a todas las variantes de la publicación.")
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
        view = df[df["score"] <= mx].sort_values("score")
        st.dataframe(view[["score", "nombre", "variantes", "largo_desc", "ficha", "faltan_requeridos", "mejoras",
                           "skus", "link"]], hide_index=True, width="stretch",
                     column_config={"score": st.column_config.ProgressColumn("Puntaje", min_value=0, max_value=100,
                                                                             format="%d"),
                                    "link": st.column_config.LinkColumn("Link", display_text="ver")})
        st.caption("Puntaje: largo y estructura de la descripción, uso de las palabras del título, ficha técnica "
                   "completa y preguntas frecuentes (GEO). Abrí **Editar publicación** para trabajar una por una.")

# ---------------------------------------------------------------- 2. editar una
with tab_ed:
    df = analizadas()
    if df is None or df.empty:
        st.info("Primero analizá el catálogo en la pestaña **📊 Analizar catálogo**.")
    else:
        opts = df.sort_values("score")
        pid = st.selectbox("Publicación (ordenadas de peor a mejor puntaje)", opts["pub"].tolist(),
                           format_func=lambda p: f"[{int(opts.set_index('pub').loc[p, 'score'])}] "
                                                 f"{opts.set_index('pub').loc[p, 'nombre']}",
                           key="cont_pid")
        row = opts.set_index("pub").loc[pid]
        rep = row["item_id"]
        item = {it["id"]: it for it in multiget(client, [rep])}.get(rep, {})
        cat = ct.category_attributes(client, item.get("category_id")) if item else []
        st.markdown(f"**{item.get('title', row['nombre'])}** · {row['variantes']} variante(s) · "
                    f"[ver en MeLi]({row['link']}) · puntaje **{row['score']}** — {row['mejoras'] or 'sin observaciones'}")

        k_new = f"cont_new_{rep}"
        st.session_state.setdefault(k_new, row["descripcion"])
        b1, b2, b3 = st.columns([1, 1, 2])
        extra = b3.text_input("Indicaciones para la IA (opcional)", key=f"cont_extra_{rep}",
                              placeholder="Ej: destacar que es para césped natural, tono más técnico")
        if b1.button("✨ Sugerir con IA", disabled=not api_key, key=f"cont_ai_{rep}",
                     help=None if api_key else "Cargá ANTHROPIC_API_KEY en los secrets para usar la IA."):
            with st.spinner("Generando con Claude…"):
                try:
                    sug, costo = ct.ai_suggest(api_key, secret("ANTHROPIC_MODEL", "claude-sonnet-4-5"), item,
                                               row["descripcion"], cat, extra)
                    st.session_state[k_new] = sug.get("descripcion", "")
                    st.session_state[f"cont_attrsug_{rep}"] = {a["id"]: a.get("valor") for a in sug.get("atributos", [])
                                                               if a.get("id") and a.get("valor")}
                    st.session_state["cont_gasto"] = st.session_state.get("cont_gasto", 0) + costo
                    st.toast(f"Listo · costo aprox. US$ {costo:.3f}")
                except Exception as e:  # noqa: BLE001
                    st.error(str(e))
        if b2.button("↩️ Volver a la actual", key=f"cont_reset_{rep}"):
            st.session_state[k_new] = row["descripcion"]

        c1, c2 = st.columns(2)
        c1.text_area("Descripción actual", row["descripcion"], height=420, disabled=True, key=f"cont_cur_{rep}")
        nueva = c2.text_area("Descripción nueva (editable)", height=420, key=k_new)
        c2.caption(f"{len(nueva)} caracteres · texto plano (sin HTML, links, teléfonos ni emojis)")
        limpia = ct.limpiar(nueva)
        if limpia != nueva.strip():
            c2.warning("Tiene contenido que MeLi no acepta (HTML, links, emojis…): se va a limpiar al guardar.")

        st.markdown("#### Ficha técnica")
        vals = ct.item_attr_values(item)
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
            solo_falt = st.checkbox("Mostrar solo los atributos vacíos", value=True, key=f"cont_sf_{rep}")
            show_at = at[at["valor_actual"] == ""] if solo_falt else at
            at_ed = st.data_editor(show_at, hide_index=True, width="stretch", key=f"cont_at_{rep}_{len(sug)}",
                                   disabled=["id", "atributo", "valor_actual", "valores_posibles"],
                                   column_config={"valor_nuevo": st.column_config.TextColumn("Valor nuevo"),
                                                  "valores_posibles": st.column_config.TextColumn(width="large")})
            st.caption("* requerido. En los que tienen valores posibles, escribí uno de esos exactamente.")

        cambios_attr = {r["id"]: r["valor_nuevo"] for _, r in at_ed.iterrows()
                        if str(r["valor_nuevo"] or "").strip() and r["valor_nuevo"] != r["valor_actual"]} \
            if not at_ed.empty else {}
        cambia_desc = limpia != (row["descripcion"] or "").strip()
        ids = row["item_ids"].split(",")
        todas = st.checkbox(f"Aplicar a las {len(ids)} variantes de la publicación", value=True, key=f"cont_all_{rep}")
        destino = ids if todas else [rep]
        st.write(f"Cambios: {'descripción' if cambia_desc else ''}"
                 f"{' + ' if cambia_desc and cambios_attr else ''}"
                 f"{f'{len(cambios_attr)} atributos' if cambios_attr else ''}"
                 f"{'ninguno' if not cambia_desc and not cambios_attr else ''} → {len(destino)} publicación(es)")
        if st.button("💾 Guardar en MeLi", type="primary", disabled=not (cambia_desc or cambios_attr),
                     key=f"cont_save_{rep}"):
            def job(r):
                if cambia_desc:
                    ct.set_description(client, r["item_id"], limpia)
                if cambios_attr:
                    ct.set_attributes(client, r["item_id"], cambios_attr)

            res = run_bulk([{"item_id": i} for i in destino], job, label="Guardando")
            show_results(res, f"resultado_contenido_{datetime.now():%Y%m%d_%H%M}.xlsx")
            if (res["resultado"] == "OK").all():
                df.loc[df["pub"] == pid, "descripcion"] = limpia
                df.loc[df["pub"] == pid, "largo_desc"] = len(limpia)

        if st.session_state.get("cont_gasto"):
            st.caption(f"Gasto de IA en esta sesión: US$ {st.session_state['cont_gasto']:.3f}")

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
                with st.expander(f"{p['nombre']} · {len(p['item_ids'].split(','))} variante(s)", expanded=i < 2):
                    a, b = st.columns(2)
                    a.text_area("Actual", p["actual"], height=300, disabled=True, key=f"q_cur_{i}")
                    p["nueva"] = b.text_area("Propuesta (editable)", p["nueva"], height=300, key=f"q_new_{i}")
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

# ---------------------------------------------------------------- 4. Excel ida y vuelta
with tab_xl:
    df = analizadas()
    if df is None or df.empty:
        st.info("Primero analizá el catálogo en **📊 Analizar catálogo**.")
    else:
        st.markdown("1. Bajá el Excel · 2. Completá la columna **descripcion_nueva** (las vacías no se tocan) · "
                    "3. Subilo · 4. Revisá y aplicá a todas las variantes.")
        out = df[["pub", "nombre", "item_ids", "score", "descripcion"]].rename(columns={"descripcion": "descripcion_actual"})
        out["descripcion_nueva"] = ""
        buf = io.BytesIO()
        out.to_excel(buf, index=False)
        st.download_button("⬇️ Bajar Excel de descripciones", buf.getvalue(),
                           file_name=f"descripciones_{datetime.now():%Y%m%d}.xlsx")
        up = st.file_uploader("Subir Excel completado", type=["xlsx"], key="cont_up")
        if up:
            x = pd.read_excel(up, dtype=str).fillna("")
            x = x[x["descripcion_nueva"].str.strip() != ""]
            if x.empty:
                st.warning("No hay filas con descripcion_nueva.")
            else:
                x["descripcion_nueva"] = x["descripcion_nueva"].map(ct.limpiar)
                x["largo"] = x["descripcion_nueva"].str.len()
                st.dataframe(x[["nombre", "item_ids", "largo", "descripcion_nueva"]], hide_index=True, width="stretch")
                filas = [{"publicacion": r["nombre"], "item_id": iid, "desc": r["descripcion_nueva"]}
                         for _, r in x.iterrows() for iid in str(r["item_ids"]).split(",") if iid]
                ok = st.checkbox(f"Confirmo actualizar la descripción de {len(filas)} publicaciones "
                                 f"({len(x)} artículos)", key="cont_xl_ok")
                if st.button("💾 Aplicar Excel", type="primary", disabled=not ok):
                    res = run_bulk(filas, lambda r: ct.set_description(client, r["item_id"], r["desc"]), label="Guardando")
                    show_results(res[["publicacion", "item_id", "resultado", "error", "procesado"]],
                                 f"resultado_excel_desc_{datetime.now():%Y%m%d_%H%M}.xlsx")
