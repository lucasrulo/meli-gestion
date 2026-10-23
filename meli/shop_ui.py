"""Piezas de UI compartidas por las páginas de Shopify: tienda, catálogo y selector de productos."""
import time

import pandas as pd
import streamlit as st

from .catalog import norm
from .shop_bulk import catalogo
from .shop_ops import COLL_VERSION
from .shopify import ShopifyClient, ShopifyError, stores

ESTADOS = {"ACTIVE": "🟢 Activo", "UNLISTED": "🔗 No listado", "DRAFT": "📝 Borrador", "ARCHIVED": "📦 Archivado"}


def pick_store(key: str = "shop_store") -> str | None:
    st_ = stores()
    if not st_:
        st.warning("No hay tiendas Shopify conectadas. Andá a **Cuentas → Conectar tienda**.")
        st.stop()
    opts = list(st_)
    return st.sidebar.selectbox("Tienda Shopify", opts, key=key, format_func=lambda k: st_[k]["nombre"])


def cargar(tienda: str):
    c1, c2 = st.columns([4, 1], vertical_alignment="center")
    refresh = c2.button("🔄 Releer catálogo", key=f"cat_ref_{tienda}", width="stretch",
                        help="Lee de nuevo todo el catálogo de Shopify (operación masiva, 1–3 min).")
    t0 = time.time()
    try:
        with st.spinner("Leyendo el catálogo completo de Shopify (operación masiva)…"):
            P, V, M, MF = catalogo(tienda, refresh=refresh)
    except ShopifyError as e:
        st.error(str(e))
        st.stop()
    leido = st.session_state.get(f"cat_nonce_{tienda}")
    c1.caption(f"{len(P)} productos · {len(V)} variantes · {len(M)} fotos"
               + (f" · leído {time.strftime('%H:%M', time.localtime(leido))}" if leido else "")
               + (f" · {time.time() - t0:.0f}s" if time.time() - t0 > 2 else ""))
    return P, V, M, MF


def _match_codigos(P: pd.DataFrame, texto: str) -> tuple[pd.DataFrame, list[str]]:
    codigos = [c.strip() for c in texto.replace(",", "\n").replace(";", "\n").splitlines() if c.strip()]
    if not codigos:
        return P.iloc[0:0], []
    idx = {}
    for i, r in P.iterrows():
        idx[i] = ([norm(c) for c in r["codigos"]], str(r["handle"] or "").lower())
    hit, faltan = set(), []
    for c in codigos:
        n, lo = norm(c), c.lower()
        found = [i for i, (cods, h) in idx.items() if any(x.startswith(n) for x in cods) or (len(lo) >= 5 and lo in h)]
        hit |= set(found)
        if not found:
            faltan.append(c)
    return P.loc[sorted(hit)], faltan


def selector(P: pd.DataFrame, k: str, extra_cols: list[str] | None = None, default_modo: str = "Pegar códigos") -> pd.DataFrame:
    """Elegir productos por códigos pegados o por filtros. Devuelve los tildados."""
    modo = st.segmented_control("Elegir productos", ["Pegar códigos", "Filtros"], default=default_modo,
                                key=f"{k}_selmodo") or default_modo
    if modo == "Pegar códigos":
        txt = st.text_area("Códigos de artículo, SKUs o handles (uno por línea, se puede pegar desde Excel)",
                           key=f"{k}_cod", height=110, placeholder="P14313300000310SS25\nK134-KSA02\n…")
        sel, faltan = _match_codigos(P, txt)
        if faltan:
            st.warning(f"No encontré {len(faltan)}: " + ", ".join(faltan[:30]) + ("…" if len(faltan) > 30 else ""))
    else:
        f1, f2, f3, f4 = st.columns(4)
        est = f1.multiselect("Estado", list(ESTADOS), format_func=ESTADOS.get, key=f"{k}_est")
        tipos = sorted(x for x in P["tipo"].dropna().unique() if x)
        tip = f2.multiselect("Tipo de producto", tipos, key=f"{k}_tipo")
        tags_all = sorted({t for ts in P["tags"] for t in ts})
        tg = f3.multiselect("Con tag", tags_all, key=f"{k}_tag")
        stock = f4.selectbox("Stock", ["Todos", "Con stock", "Sin stock"], key=f"{k}_stock")
        q = st.text_input("Buscar en título / SKU", key=f"{k}_q")
        sel = P
        if est:
            sel = sel[sel["estado"].isin(est)]
        if tip:
            sel = sel[sel["tipo"].isin(tip)]
        if tg:
            sel = sel[sel["tags"].apply(lambda ts: any(t in ts for t in tg))]
        if stock != "Todos":
            sel = sel[(sel["stock"].fillna(0) > 0) == (stock == "Con stock")]
        if q:
            ql = q.lower()
            sel = sel[sel["titulo"].str.lower().str.contains(ql, regex=False, na=False)
                      | sel["skus"].str.lower().str.contains(ql, regex=False, na=False)]
    if sel.empty:
        st.caption("Sin productos elegidos todavía.")
        return sel
    cols = ["foto", "titulo", "estado", "stock", "n_fotos", "skus"] + (extra_cols or [])
    view = sel[["product_id"] + cols].copy()
    view.insert(0, "✔", True)
    view["estado"] = view["estado"].map(lambda x: ESTADOS.get(x, x))
    ed = st.data_editor(view, hide_index=True, width="stretch", key=f"{k}_ed_{len(view)}_{hash(tuple(view['product_id']))}",
                        height=min(40 + 52 * len(view), 420), row_height=50,
                        disabled=[c for c in view.columns if c != "✔"],
                        column_order=["✔"] + cols,
                        column_config={"✔": st.column_config.CheckboxColumn(width="small"),
                                       "foto": st.column_config.ImageColumn("", width="small"),
                                       "titulo": st.column_config.TextColumn("Producto", width="large"),
                                       "n_fotos": st.column_config.NumberColumn("Fotos"),
                                       "skus": st.column_config.TextColumn("SKUs")})
    elegidos = sel[sel["product_id"].isin(ed.loc[ed["✔"], "product_id"])]
    st.caption(f"**{len(elegidos)}** de {len(sel)} productos tildados.")
    return elegidos


def ejecutar_ui(boton: str, n: int, key: str, confirm_txt: str | None = None) -> bool:
    """Checkbox de confirmación + botón. True si hay que ejecutar."""
    c1, c2 = st.columns([2, 1], vertical_alignment="center")
    ok = c1.checkbox(confirm_txt or f"Confirmo aplicar a {n} producto(s)", key=f"{key}_ok_{n}")
    return c2.button(boton, type="primary", disabled=not (ok and n), key=f"{key}_go", width="stretch")


def progreso(texto: str):
    bar = st.progress(0.0, text=texto)
    return lambda p: bar.progress(min(max(p, 0.0), 1.0), text=f"{texto} {p * 100:.0f}%")


@st.cache_data(ttl=600, show_spinner=False)
def publicaciones(key: str) -> list[dict]:
    cli = ShopifyClient(key)
    for q in ("{ publications(first: 30) { nodes { id name } } }", "{ publications(first: 30) { nodes { id catalog { title } } } }"):
        try:
            nodes = cli.gql(q)["publications"]["nodes"]
            return [{"id": n["id"], "nombre": n.get("name") or (n.get("catalog") or {}).get("title") or n["id"]} for n in nodes]
        except ShopifyError:
            continue
    return []


@st.cache_data(ttl=600, show_spinner=False)
def colecciones(key: str, nonce: int) -> pd.DataFrame:
    cli = ShopifyClient(key)
    q = """query($c: String) { collections(first: 250, after: $c) { pageInfo { hasNextPage endCursor }
             nodes { id title handle ruleSet { appliedDisjunctively } productsCount { count } } } }"""
    rows, cur = [], None
    while True:
        d = cli.gql(q, {"c": cur}, version=COLL_VERSION)["collections"]
        rows += [{"id": n["id"], "titulo": n["title"], "handle": n["handle"],
                  "tipo": "Automática" if n.get("ruleSet") else "Manual",
                  "productos": (n.get("productsCount") or {}).get("count")} for n in d["nodes"]]
        if not d["pageInfo"]["hasNextPage"]:
            break
        cur = d["pageInfo"]["endCursor"]
    return pd.DataFrame(rows, columns=["id", "titulo", "handle", "tipo", "productos"])
