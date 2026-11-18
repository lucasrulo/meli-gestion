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

hero("Colores Shopify", "Ver y cambiar el color de muchos productos, en todas las tiendas a la vez.", "SHOPIFY · COLORES")

t_colr = st.container()


def _filas(sel: pd.DataFrame, antes_col, despues) -> list[dict]:
    return [{"id": r["product_id"], "label": r["titulo"],
             "antes": r[antes_col] if isinstance(antes_col, str) else antes_col(r),
             "despues": despues(r) if callable(despues) else despues} for _, r in sel.iterrows()]



# ================================================================ colores (todas las tiendas)
with t_colr:
    from meli.catalog import norm as _normc
    from meli.selector_marca import corto as _corto
    from meli.shop_bulk import catalogo as _cat_c, color_por_producto, fuentes_color
    from meli.ui import caja_texto
    st.caption("Pegá un listado de **modelo-color** (opcional: 2ª columna con el **color nuevo**). Lo busca en **todas "
               "las tiendas**, te trae el color cargado y podés cambiarlo en masa (también pegando una columna entera "
               "en *Color nuevo*). Se puede deshacer desde **Historial**.")
    todas_c = stores()
    t_sel = st.multiselect("Tiendas", list(todas_c), default=list(todas_c), key="colr_tiendas",
                           format_func=lambda k: _corto(todas_c[k]["nombre"]))
    txt = caja_texto("Modelo-color · Color nuevo (opcional)", "colr_txt", "🔎 Buscar colores", height=150,
                     placeholder="K1342233W-KSA02\tNegro/Blanco\nP14313300000310SS25\tAzul marino")
    pedidos: dict[str, str] = {}
    for ln in txt.splitlines():
        if not ln.strip():
            continue
        partes = [x.strip() for x in (ln.split("\t") if "\t" in ln else ln.split(";"))]
        cod = partes[0].upper()
        if cod.lower() in ("modelo_color", "modelo-color", "modelo", "sku"):
            continue
        pedidos[cod] = partes[1] if len(partes) > 1 else ""

    if pedidos and t_sel:
        filas_c, fuentes_t = [], {}
        bar = st.progress(0.0, text="Leyendo catálogos…")
        for i, k in enumerate(t_sel, 1):
            bar.progress((i - 1) / len(t_sel), text=f"Leyendo {_corto(todas_c[k]['nombre'])}…")
            try:
                Pk, Vk, _, MFk = _cat_c(k)
            except ShopifyError as e:
                st.warning(f"{todas_c[k]['nombre']}: {e}")
                continue
            fs = fuentes_color(Pk, MFk)
            fuentes_t[k] = fs
            elegida = st.session_state.get(f"colr_fuente_{k}") or (next(iter(fs)) if fs else None)
            cp = color_por_producto(Pk, MFk, elegida).set_index("product_id") if elegida else None
            vv = Vk[Vk["sku"].fillna("") != ""].copy()
            vv["mc"] = vv["sku"].map(lambda x: _normc(strip_size(x) or ""))
            vv["skn"] = vv["sku"].map(_normc)
            info = Pk.set_index("product_id")
            for cod, nuevo in pedidos.items():
                n = _normc(cod)
                pids = vv[(vv["mc"] == n) | (vv["skn"] == n)]["product_id"].unique()
                for pid in pids:
                    c = cp.loc[pid] if cp is not None and pid in cp.index else None
                    filas_c.append({"tienda": k, "marca": _corto(todas_c[k]["nombre"]), "modelo_color": cod,
                                    "producto": info.loc[pid, "titulo"], "foto": info.loc[pid, "foto"],
                                    "product_id": pid, "fuente": elegida or "",
                                    "color_actual": "" if c is None else c["color"], "color_nuevo": nuevo,
                                    "option_id": None if c is None else c["option_id"],
                                    "value_id": None if c is None else c["value_id"],
                                    "n_valores": 0 if c is None else c["n_valores"],
                                    "mf_type": None if c is None else c["mf_type"],
                                    "mf_raw": None if c is None else c["mf_raw"]})
        bar.empty()

        # ---- de dónde sale el color en cada tienda (se puede cambiar)
        etiqueta = lambda f: "Opción de variante «Color»" if f == "opcion" else f"Metacampo {f[5:]}"  # noqa: E731
        with st.expander("⚙️ De dónde se lee / escribe el color en cada tienda", expanded=False):
            for k, fs in fuentes_t.items():
                if not fs:
                    st.caption(f"**{_corto(todas_c[k]['nombre'])}**: no encontré el color (ni opción Color ni metacampo "
                               "con «color» en el nombre).")
                    continue
                st.selectbox(_corto(todas_c[k]["nombre"]), list(fs), key=f"colr_fuente_{k}",
                             format_func=lambda f, fs=fs: f"{etiqueta(f)} · {fs[f]} productos")

        encontrados = {f["modelo_color"] for f in filas_c}
        faltan = [c for c in pedidos if c not in encontrados]
        if faltan:
            st.warning(f"No encontré {len(faltan)} en las tiendas elegidas: " + ", ".join(faltan[:30]))
        dfc = pd.DataFrame(filas_c)
        if not dfc.empty:
            m1, m2, m3 = st.columns(3)
            m1.metric("Modelo-color", dfc["modelo_color"].nunique())
            m2.metric("Productos", len(dfc))
            m3.metric("Tiendas", dfc["tienda"].nunique())
            vista = dfc.assign(fuente=dfc["fuente"].map(lambda f: etiqueta(f) if f else "—"))
            ed = st.data_editor(
                vista[["marca", "foto", "modelo_color", "producto", "fuente", "color_actual", "color_nuevo"]],
                hide_index=True, width="stretch", row_height=50, height=min(40 + 52 * len(vista), 520),
                key=f"colr_ed_{hash(tuple(dfc['product_id']))}_{hash(tuple(fuentes_t))}",
                disabled=["marca", "foto", "modelo_color", "producto", "fuente", "color_actual"],
                column_config={"foto": st.column_config.ImageColumn("", width="small"),
                               "producto": st.column_config.TextColumn("Producto", width="large"),
                               "color_actual": "Color actual",
                               "color_nuevo": st.column_config.TextColumn("✏️ Color nuevo (podés pegar una columna)",
                                                                          width="medium")})
            st.download_button("⬇️ Excel de colores", to_xlsx(dfc[["marca", "modelo_color", "producto", "color_actual",
                                                                  "color_nuevo"]]), "colores.xlsx", key="colr_xlsx")
            dfc["color_nuevo"] = ed["color_nuevo"].fillna("").astype(str).str.strip().values
            cambia = dfc[(dfc["color_nuevo"] != "") & (dfc["color_nuevo"] != dfc["color_actual"])].copy()
            err = cambia[(cambia["fuente"] == "") | ((cambia["fuente"] == "opcion") & (cambia["value_id"].isna()))]
            if not err.empty:
                st.warning(f"{len(err)} producto(s) no se pueden cambiar: sin opción/metacampo de color, o con varios "
                           "colores en el mismo producto. " + ", ".join(err["modelo_color"].head(15)))
            cambia = cambia.drop(err.index)
            if ejecutar_ui("🎨 Aplicar colores", len(cambia), "colr",
                           f"Confirmo cambiar el color de {len(cambia)} producto(s) en {cambia['tienda'].nunique()} tienda(s)"):
                for (k, fuente), g in cambia.groupby(["tienda", "fuente"]):
                    nom = _corto(todas_c[k]["nombre"])
                    if fuente == "opcion":
                        filas = [{"id": r["product_id"], "label": f"{r['producto']} ({r['modelo_color']})",
                                  "meta": {"option_id": r["option_id"], "value_id": r["value_id"]},
                                  "antes": r["color_actual"], "despues": r["color_nuevo"]} for _, r in g.iterrows()]
                        res = ops.aplicar(k, "color_opcion", filas, f"{nom}: color de {len(filas)} productos",
                                          progress=progreso(f"Colores {nom}…"))
                    else:
                        ns, key_ = fuente[5:].split(".", 1)
                        tipo = g["mf_type"].dropna().mode().iloc[0] if g["mf_type"].notna().any() else "single_line_text_field"
                        val = (lambda v: json.dumps([v], ensure_ascii=False)) if str(tipo).startswith("list.") else (lambda v: v)
                        filas = [{"id": r["product_id"], "label": f"{r['producto']} ({r['modelo_color']})",
                                  "antes": r["mf_raw"] if isinstance(r["mf_raw"], str) else None,
                                  "despues": val(r["color_nuevo"])} for _, r in g.iterrows()]
                        res = ops.aplicar(k, "metacampos", filas, f"{nom}: color ({ns}.{key_}) de {len(filas)} productos",
                                          meta={"namespace": ns, "key": key_, "type": tipo},
                                          progress=progreso(f"Colores {nom}…"))
                    st.markdown(f"**{nom}**")
                    ops.mostrar_resultado(res)
