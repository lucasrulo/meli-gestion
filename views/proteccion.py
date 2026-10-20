import io
from datetime import datetime

import pandas as pd
import streamlit as st

from meli.theme import hero

from meli import marca
from meli.api import MeliError
from meli.auth import get_token_manager
from meli.excel import to_number
from meli.ui import pick_account

hero("Protección de marca", "Detección de publicaciones sospechosas de terceros y registro de denuncias.", "MARCA · RIESGO")
st.caption("Encuentra publicaciones de terceros con señales de falsificación, agrupa por vendedor y arma el listado "
           "para denunciar en el Programa de Protección de Marca de MeLi (o pasarle a la marca). "
           "El puntaje es una **ayuda para priorizar**, no una prueba: revisá cada publicación antes de denunciar.")
client = pick_account()
own_ids = set(get_token_manager().accounts().keys())
store = marca.ProteccionStore()


def load_store(force=False):
    if force or "prot_store" not in st.session_state:
        st.session_state["prot_store"] = store.load()
    return st.session_state["prot_store"]


data = load_store()
autorizados = set(map(str, data.get("autorizados", [])))
denuncias = data.get("denuncias", {})

# ---------------------------------------------------------------- parámetros
with st.expander("⚙️ Criterios", expanded=False):
    c1, c2, c3 = st.columns(3)
    thr = c1.slider("Precio sospechoso si es menor a (% de la referencia)", 30, 95, 60, 5) / 100
    excl_oficiales = c2.checkbox("Excluir tiendas oficiales", value=True)
    solo_nuevos = c3.checkbox("Solo productos nuevos", value=True)
    st.caption("Referencia de precio por búsqueda: la que pongas a mano → si no, la mediana de tu tienda en esos "
               "resultados → si no, la de tiendas oficiales. Siempre se excluyen tus cuentas y los vendedores autorizados.")

tab_buscar, tab_links, tab_den, tab_aut = st.tabs(
    ["🔎 Buscar en MeLi", "🔗 Analizar links", f"📋 Denunciadas ({len(denuncias)})", f"✅ Autorizados ({len(autorizados)})"])


def run_pipeline(groups: dict[str, list[str]], manual_refs: dict):
    """groups: {busqueda: [item_ids]}"""
    all_ids = list(dict.fromkeys(i for ids in groups.values() for i in ids))
    if not all_ids:
        st.warning("No se encontraron publicaciones.")
        return
    with st.spinner(f"Leyendo {len(all_ids)} publicaciones…"):
        items = {it["id"]: it for it in marca.fetch_items(client, all_ids)}
    rows = [marca.item_row(items[i], q) for q, ids in groups.items() for i in ids if i in items]
    df = pd.DataFrame(rows)
    if df.empty:
        st.warning("MeLi no devolvió datos de esas publicaciones.")
        return
    refs = marca.reference_prices(df, own_ids, manual_refs)
    df = df[~df["seller_id"].isin(own_ids | autorizados)]
    if excl_oficiales:
        df = df[~df["tienda_oficial"]]
    if solo_nuevos:
        df = df[df["condicion"].fillna("new") == "new"]
    df = df[df["estado"].fillna("active") == "active"]
    if df.empty:
        st.info("Después de excluir tus cuentas, autorizados y tiendas oficiales no quedó nada.")
        return
    sellers = df["seller_id"].value_counts().index.tolist()[:400]
    with st.spinner(f"Consultando {len(sellers)} vendedores…"):
        sinfo = marca.sellers_info(client, sellers)
    st.session_state["prot_df"] = marca.score(df, refs, thr, sinfo, denuncias)
    st.session_state["prot_refs"] = refs


# ---------------------------------------------------------------- buscar
with tab_buscar:
    st.markdown("Una búsqueda por línea, como la escribiría un comprador. Opcional: TAB y **precio de referencia**.")
    txt = st.text_area("Búsquedas", height=140, key="prot_q",
                       placeholder="botines kappa kombat\t104999\ncampera columbia omni heat\ncrocs classic clog\t69999")
    maxr = st.select_slider("Resultados por búsqueda", [50, 100, 200, 300, 500, 1000], 300)
    if st.button("🔎 Buscar", type="primary", key="prot_go"):
        groups, manual, blocked = {}, {}, False
        lines = [l for l in (txt or "").splitlines() if l.strip()]
        prog = st.progress(0.0)
        for n, line in enumerate(lines, 1):
            parts = [p.strip() for p in line.split("\t")]
            q = parts[0]
            if len(parts) > 1 and to_number(parts[1]):
                manual[q] = to_number(parts[1])
            try:
                groups[q] = marca.search_ids(client, q, maxr)
            except MeliError as e:
                if e.status in (401, 403):
                    st.error("MeLi no permite la búsqueda general desde esta app (" + str(e)[:160] + "). "
                             "Usá la pestaña **Analizar links**: buscás en mercadolibre.com.ar, copiás los links y la "
                             "app hace el resto.")
                    blocked = True
                    break
                st.warning(f"«{q}»: {e}")
            prog.progress(n / len(lines), text=f"{q}: {len(groups.get(q, []))} resultados")
        prog.empty()
        if not blocked:
            run_pipeline(groups, manual)

# ---------------------------------------------------------------- links
with tab_links:
    st.markdown("Pegá links de publicaciones (o IDs MLA…) y/o links de catálogo `/p/MLA…` (trae a todos los "
                "vendedores de esa ficha). Opcional: precio de referencia para el lote.")
    links = st.text_area("Links", height=140, key="prot_links",
                         placeholder="https://articulo.mercadolibre.com.ar/MLA-1234567890-botines-...\n"
                                     "https://www.mercadolibre.com.ar/botines-kappa/p/MLA12345678")
    c1, c2 = st.columns([1, 3])
    ref_links = c1.number_input("Precio de referencia", min_value=0, value=0, step=1000, key="prot_ref_links")
    if st.button("🔗 Analizar", type="primary", key="prot_links_go"):
        items, products = marca.parse_links(links)
        groups = {"links": items}
        for pid in products:
            groups[f"ficha {pid}"] = marca.product_item_ids(client, pid)
        manual = {k: ref_links for k in groups} if ref_links else {}
        run_pipeline(groups, manual)

# ---------------------------------------------------------------- resultados
df = st.session_state.get("prot_df")
if df is not None and not df.empty:
    st.divider()
    st.subheader("Resultados")
    refs = st.session_state.get("prot_refs", {})
    st.caption("Referencias: " + " · ".join(
        f"{q}: {('$' + format(int(r), ',').replace(',', '.')) if r else '—'} ({src})" for q, (r, src) in refs.items()))
    min_score = st.slider("Mostrar desde puntaje", 0, 100, 40, 5)
    view = df[df["score"] >= min_score].copy()
    m = st.columns(4)
    m[0].metric("Publicaciones analizadas", len(df))
    m[1].metric(f"Sospechosas (≥{min_score})", len(view))
    m[2].metric("Vendedores sospechosos", view["seller_id"].nunique())
    m[3].metric("Ya denunciadas", int(view["denunciada"].sum()))

    t1, t2 = st.tabs(["📄 Publicaciones", "👤 Vendedores"])
    with t1:
        view.insert(0, "denunciar", False)
        cols = ["denunciar", "score", "señales", "foto", "titulo", "precio", "ref", "precio_vs_ref_%", "vendedor",
                "seller_id", "provincia", "ciudad", "vendidos", "stock", "busqueda", "item_id", "link", "denunciada"]
        cols = [c for c in cols if c in view]
        ed = st.data_editor(
            view[cols], hide_index=True, width="stretch", key="prot_ed",
            disabled=[c for c in cols if c != "denunciar"],
            column_config={
                "foto": st.column_config.ImageColumn("Foto", width="small"),
                "link": st.column_config.LinkColumn("Link", display_text="abrir"),
                "score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100, format="%d"),
                "precio": st.column_config.NumberColumn("Precio", format="localized"),
                "ref": st.column_config.NumberColumn("Ref.", format="localized"),
            },
        )
        sel = view[ed["denunciar"].values]
        c1, c2 = st.columns(2)
        if c1.button(f"📌 Marcar {len(sel)} como denunciadas", disabled=sel.empty):
            st.session_state["prot_store"] = store.add_denuncias(sel.to_dict("records"))
            st.session_state["prot_df"]["denunciada"] |= st.session_state["prot_df"]["item_id"].isin(sel["item_id"])
            st.success(f"Registradas {len(sel)} denuncias.")
            st.rerun()
        if not sel.empty:
            st.text_area("Links seleccionados (copiar para la denuncia)", "\n".join(sel["link"].dropna()), height=120)

    with t2:
        vs = marca.sellers_summary(view)
        st.dataframe(vs, hide_index=True, width="stretch",
                     column_config={"perfil": st.column_config.LinkColumn("Perfil", display_text="ver"),
                                    "precio_min": st.column_config.NumberColumn("Precio mín.", format="localized")})
        add = st.multiselect("Agregar vendedores a **autorizados** (no vuelven a aparecer)", vs["seller_id"].tolist(),
                             format_func=lambda s: f"{vs.set_index('seller_id').loc[s, 'vendedor']} ({s})")
        if st.button("✅ Agregar a autorizados", disabled=not add):
            st.session_state["prot_store"] = store.set_autorizados(list(autorizados | set(add)))
            st.session_state["prot_df"] = df[~df["seller_id"].isin(add)]
            st.rerun()

    buf = io.BytesIO()
    with pd.ExcelWriter(buf) as xw:
        view.drop(columns=["denunciar", "foto"], errors="ignore").to_excel(xw, sheet_name="Publicaciones", index=False)
        marca.sellers_summary(view).to_excel(xw, sheet_name="Vendedores", index=False)
    st.download_button("⬇️ Excel para denuncia (publicaciones + vendedores)", buf.getvalue(),
                       file_name=f"proteccion_marca_{datetime.now():%Y%m%d_%H%M}.xlsx")

# ---------------------------------------------------------------- denunciadas
with tab_den:
    if not denuncias:
        st.info("Todavía no registraste denuncias.")
    else:
        dd = pd.DataFrame([{"item_id": k, **v} for k, v in denuncias.items()]).sort_values("fecha", ascending=False)
        st.dataframe(dd, hide_index=True, width="stretch",
                     column_config={"link": st.column_config.LinkColumn("Link", display_text="abrir")})
        c1, c2 = st.columns(2)
        if c1.button("🔄 Verificar si siguen activas"):
            with st.spinner("Consultando MeLi…"):
                its = marca.fetch_items(client, dd["item_id"].tolist())
            estados = {it["id"]: it.get("status") for it in its}
            for i in dd["item_id"]:
                estados.setdefault(i, "no disponible")
            st.session_state["prot_store"] = store.update_estados(estados)
            bajas = sum(1 for e in estados.values() if e != "active")
            st.success(f"{bajas} de {len(estados)} ya no están activas.")
            st.rerun()
        quitar = c2.multiselect("Quitar del registro", dd["item_id"].tolist(), key="prot_rm")
        if quitar and c2.button("Quitar"):
            st.session_state["prot_store"] = store.remove_denuncias(quitar)
            st.rerun()
        buf2 = io.BytesIO()
        dd.to_excel(buf2, index=False)
        st.download_button("⬇️ Excel de denunciadas", buf2.getvalue(), file_name="denunciadas.xlsx")

# ---------------------------------------------------------------- autorizados
with tab_aut:
    st.caption("Revendedores autorizados o cuentas que no querés ver en los resultados (ID de vendedor, uno por línea).")
    txt_aut = st.text_area("Autorizados", "\n".join(sorted(autorizados)), height=160, key="prot_aut")
    if st.button("Guardar autorizados"):
        ids = [x.strip() for x in txt_aut.splitlines() if x.strip()]
        st.session_state["prot_store"] = store.set_autorizados(ids)
        st.success("Guardado.")
        st.rerun()
