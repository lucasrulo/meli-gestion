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

hero("Descargar productos", "Excel de todos los productos por modelo-color (o por SKU), de todas las marcas.", "SHOPIFY · EXCEL")

t_dl = st.container()


def _filas(sel: pd.DataFrame, antes_col, despues) -> list[dict]:
    return [{"id": r["product_id"], "label": r["titulo"],
             "antes": r[antes_col] if isinstance(antes_col, str) else antes_col(r),
             "despues": despues(r) if callable(despues) else despues} for _, r in sel.iterrows()]



# ================================================================ 4. descargar productos (todas las marcas) por modelo + color
def _talle(variante: str) -> str:
    v = str(variante or "")
    return v.split("/")[-1].strip() if "/" in v else v.strip()


with t_dl:
    from datetime import date as _date

    from meli.shop_bulk import catalogo as _catalogo
    from meli.selector_marca import corto
    st.caption("Productos de **todas las marcas** colapsados a una fila por **modelo + color** (talles juntos), con su "
               "**fecha de creación**. Mountain Hardwear y Sorel se separan por vendor dentro de su tienda.")
    todas = stores()
    c1, c2 = st.columns([1.4, 1])
    sel_t = c1.multiselect("Tiendas a incluir", list(todas), default=list(todas), key="dl_tiendas",
                           format_func=lambda k: corto(todas[k]["nombre"]))
    todo = c2.checkbox("Traer todos los productos (ignorar fechas)", value=True, key="dl_todo")
    if todo:
        c2.caption("Se traen **todos** los productos, sin filtrar por fecha de creación.")
        desde = hasta = None
    else:
        d1, d2 = c2.columns(2)
        desde = d1.date_input("Creados desde", _date.today().replace(day=1), key="dl_desde", format="DD/MM/YYYY")
        hasta = d2.date_input("Hasta", _date.today(), key="dl_hasta", format="DD/MM/YYYY")
    est_dl = st.multiselect("Estados", list(ESTADOS), default=list(ESTADOS), format_func=ESTADOS.get, key="dl_est")
    sku_full = st.checkbox("Agregar SKU completo", value=False, key="dl_sku",
                           help="Agrega la columna SKU (con talle): una fila por cada talle, así que cada modelo-color "
                                "se repite tantas veces como talles tenga. Suma también EAN, talle y stock de ese talle.")
    if st.button("⬇️ Generar Excel de productos", type="primary", width="stretch", disabled=not sel_t, key="dl_go"):
        filas, bar = [], st.progress(0.0, text="Leyendo catálogos…")
        for i, k in enumerate(sel_t, 1):
            bar.progress((i - 1) / len(sel_t), text=f"Leyendo {corto(todas[k]['nombre'])}…")
            try:
                Pk, Vk, _, MFk = _catalogo(k)
            except ShopifyError as e:
                st.warning(f"{todas[k]['nombre']}: {e}")
                continue
            if est_dl:
                Pk = Pk[Pk["estado"].isin(est_dl)]
            if desde:
                cr = pd.to_datetime(Pk["creado"], errors="coerce").dt.date
                Pk = Pk[(cr >= desde) & (cr <= hasta)]
            vv = Vk[Vk["product_id"].isin(Pk["product_id"])].copy()
            vv["modelo_color"] = vv["sku"].map(lambda x: strip_size(x) if x else None).fillna("(sin SKU)")
            vv["talle"] = vv["variante"].map(_talle)
            info = Pk.set_index("product_id")
            from meli.shop_bulk import color_lectura
            colmap = color_lectura(k, Pk, MFk)
            for (pid, mc), g in vv.groupby(["product_id", "modelo_color"]):
                p = info.loc[pid]
                filas.append({
                    "marca": corto(todas[k]["nombre"]), "modelo_color": mc, "color": colmap.get(pid, ""),
                    "producto": p["titulo"],
                    "estado": ESTADOS.get(p["estado"], p["estado"]).split(" ", 1)[-1], "tipo": p["tipo"],
                    "vendor": p["vendor"], "talles": ", ".join(t for t in g["talle"] if t),
                    "cant_talles": len(g), "talles_con_stock": int((g["stock"].fillna(0) > 0).sum()),
                    "stock": int(g["stock"].fillna(0).sum()), "precio": g["precio"].max(),
                    "precio_tachado": g["precio_tachado"].max(), "fecha_creacion": p["creado"],
                    "tags": ", ".join(p["tags"]), "url": p["url"] or "", "foto": p["foto"] or "",
                })
                if sku_full:   # una fila por talle, con su SKU completo
                    base = filas.pop()
                    for _, v_ in g.iterrows():
                        filas.append({**base, "sku": v_["sku"] or "", "talle": v_["talle"], "ean": v_["barcode"] or "",
                                      "stock_talle": int(v_["stock"]) if pd.notna(v_["stock"]) else 0,
                                      "precio_talle": v_["precio"], "precio_tachado_talle": v_["precio_tachado"]})
        bar.empty()
        out = pd.DataFrame(filas)
        if out.empty:
            st.info("No hay productos con esos filtros.")
        else:
            if "sku" in out:
                orden = ["marca", "modelo_color", "color", "sku", "talle", "ean", "stock_talle", "precio_talle",
                         "precio_tachado_talle"]
                out = out[orden + [c for c in out.columns if c not in orden]]
                out = out.sort_values(["marca", "fecha_creacion", "modelo_color", "sku"], ascending=[True, False, True, True])
            else:
                out = out.sort_values(["marca", "fecha_creacion", "modelo_color"], ascending=[True, False, True])
            st.session_state["dl_out"] = out
    out = st.session_state.get("dl_out")
    if out is not None and not out.empty:
        m1, m2, m3 = st.columns(3)
        _mc = out.drop_duplicates(["marca", "modelo_color"])   # sin duplicar por talle
        m1.metric("Modelo-color" + (f" · {len(out):,} SKU".replace(",", ".") if "sku" in out else ""),
                  f"{len(_mc):,}".replace(",", "."))
        m2.metric("Marcas", out["marca"].nunique())
        m3.metric("Stock total", f"{int(_mc['stock'].sum()):,}".replace(",", "."))
        st.dataframe(_mc.groupby("marca").agg(modelo_color=("modelo_color", "count"), stock=("stock", "sum"),
                                              con_stock=("stock", lambda s_: int((s_ > 0).sum()))).reset_index(),
                     hide_index=True, width="stretch")
        cob = _mc.assign(color=_mc.get("color", ""), _c=_mc.get("color", pd.Series("", index=_mc.index)).fillna("").astype(str).str.strip() != "").groupby("marca")["_c"].agg(["sum", "count"])
        st.caption("🎨 Color encontrado: " + " · ".join(f"**{m}** {int(r['sum'])}/{int(r['count'])}" for m, r in cob.iterrows())
                   + ". Se toma de la opción «Color», de un metacampo con «color» en el nombre o del color estándar de "
                   "Shopify. Si sale vacío, entrá a Shopify → Productos y stock y tocá 🔄 Releer catálogo.")
        st.dataframe(out.head(200), hide_index=True, width="stretch", height=300,
                     column_config={"foto": st.column_config.ImageColumn("", width="small"),
                                    "url": st.column_config.LinkColumn("Link", display_text="ver")})
        st.download_button("⬇️ Descargar Excel", to_xlsx(out), f"productos_modelo_color_{_date.today():%Y%m%d}.xlsx",
                           type="primary", width="stretch", key="dl_xlsx")
