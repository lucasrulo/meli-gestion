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

hero("Precios Shopify", "Cargar precios por modelo-color y manejar el precio tachado, sin tocar lo demás.", "SHOPIFY · PRECIOS")
tienda = pick_store()
nombre = stores()[tienda]["nombre"]
P, V, M, MF = cargar(tienda)
api_key = secret("ANTHROPIC_API_KEY")

t_pre, t_tach = st.tabs(["💰 Cargar precios", "💲 Precio tachado"])


def _filas(sel: pd.DataFrame, antes_col, despues) -> list[dict]:
    return [{"id": r["product_id"], "label": r["titulo"],
             "antes": r[antes_col] if isinstance(antes_col, str) else antes_col(r),
             "despues": despues(r) if callable(despues) else despues} for _, r in sel.iterrows()]



# ================================================================ precio tachado (compare-at) sin tocar el precio
def _num(x) -> float | None:
    t = str(x).strip().replace("$", "").replace(" ", "")
    if not t:
        return None
    if "," in t and "." in t:
        t = t.replace(".", "").replace(",", ".") if t.rfind(",") > t.rfind(".") else t.replace(",", "")
    elif "," in t:
        t = t.replace(",", ".")
    elif t.count(".") > 1 or (t.count(".") == 1 and len(t.split(".")[1]) == 3):
        t = t.replace(".", "")  # 129.999 → miles
    try:
        return float(t)
    except ValueError:
        return None


def _redondear(v: float, modo: str) -> float:
    if modo == "A $100":
        return round(v / 100) * 100
    if modo == "A $1.000":
        return round(v / 1000) * 1000
    if modo == "Terminado en 999":
        return max(round(v / 1000) * 1000 - 1, 999)
    return round(v, 2)


with t_tach:
    st.caption("Cambia **solo el precio tachado** (*compare at price*) de todas las variantes del producto. "
               "El precio de venta **no se toca**. Se puede deshacer desde **Historial**.")
    modo_t = st.segmented_control("¿Cómo calculo el tachado?", ["% OFF", "Monto fijo", "Precio de lista + %",
                                                                "Desde Excel (código → tachado)", "Quitar tachado"],
                                  default="% OFF", key="tach_modo") or "% OFF"
    pegado: dict[str, float] = {}
    if modo_t == "Desde Excel (código → tachado)":
        from meli.ui import caja_texto
        txt = caja_texto("Pegá 2 columnas desde Excel: código (modelo-color, SKU o handle) y precio tachado",
                         "tach_pegar", "✅ Leer", placeholder="P14313300000310SS25\t129999\nK134-KSA02\t89999")
        malos, faltan = [], []
        for ln in txt.splitlines():
            partes = [x for x in ln.replace(";", "\t").split("\t") if x.strip()]
            if len(partes) < 2:
                partes = ln.rsplit(" ", 1) if ln.strip() else []
            if len(partes) < 2 or _num(partes[-1]) is None:
                if ln.strip():
                    malos.append(ln.strip())
                continue
            hit, _ = _match_codigos(P, partes[0])
            if hit.empty:
                faltan.append(partes[0].strip())
            for pid in hit["product_id"]:
                pegado[pid] = _num(partes[-1])
        if malos:
            st.warning(f"{len(malos)} línea(s) sin precio válido: " + ", ".join(malos[:10]))
        if faltan:
            st.warning(f"No encontré {len(faltan)}: " + ", ".join(faltan[:30]))
        sel = P[P["product_id"].isin(pegado)]
        if not sel.empty:
            st.caption(f"**{len(sel)}** productos encontrados.")
    else:
        sel = selector(P, "tach")

    if not sel.empty:
        c1, c2 = st.columns(2)
        valor = None
        if modo_t == "% OFF":
            valor = c1.number_input("Descuento a mostrar (%)", 1.0, 90.0, 30.0, 1.0, key="tach_pct",
                                    help="Ej. 30% → tachado = precio ÷ 0,70. El cliente ve «antes $X, ahora $precio» = 30% OFF.")
        elif modo_t == "Monto fijo":
            valor = c1.number_input("Precio tachado ($)", 0.0, step=1000.0, key="tach_fijo")
        elif modo_t == "Precio de lista + %":
            valor = c1.number_input("Tachado = precio actual + (%)", 1.0, 300.0, 40.0, 1.0, key="tach_mas")
        redondeo = c2.selectbox("Redondeo", ["Sin redondeo", "A $100", "A $1.000", "Terminado en 999"],
                                index=0 if modo_t in ("Monto fijo", "Desde Excel (código → tachado)", "Quitar tachado") else 2,
                                key="tach_red", disabled=modo_t == "Quitar tachado")

        vv = V[V["product_id"].isin(sel["product_id"])].copy()

        def _nuevo(r):
            if modo_t == "Quitar tachado":
                return None
            if modo_t == "% OFF":
                v = r["precio"] / (1 - valor / 100) if r["precio"] else None
            elif modo_t == "Monto fijo":
                v = valor
            elif modo_t == "Precio de lista + %":
                v = r["precio"] * (1 + valor / 100) if r["precio"] else None
            else:
                v = pegado.get(r["product_id"])
            return _redondear(v, redondeo) if v else None

        vv["nuevo"] = pd.to_numeric(vv.apply(_nuevo, axis=1), errors="coerce") if not vv.empty else float("nan")
        if modo_t != "Quitar tachado":
            vv["invalido"] = vv["nuevo"].isna() | (vv["nuevo"] <= vv["precio"].fillna(0))
        else:
            vv["invalido"] = False
        mismo = (vv["nuevo"].fillna(-1).round(2) == vv["precio_tachado"].fillna(-1).round(2))
        aplica = vv[~vv["invalido"] & ~mismo]

        n_inv = int(vv["invalido"].sum())
        st.caption(f"**{aplica['product_id'].nunique()}** productos · **{len(aplica)}** variantes cambian"
                   + (f" · {int(mismo.sum())} ya tienen ese tachado" if int(mismo.sum()) else "")
                   + (f" · ⚠️ {n_inv} variantes se omiten porque el tachado quedaría ≤ al precio "
                      "(Shopify no lo mostraría)" if n_inv else ""))
        if not aplica.empty:
            tit = P.set_index("product_id")["titulo"]
            prev = (aplica.assign(producto=aplica["product_id"].map(tit))
                    .groupby("product_id")
                    .agg(producto=("producto", "first"), variantes=("variant_id", "count"),
                         precio=("precio", "max"), tachado_actual=("precio_tachado", "max"), tachado_nuevo=("nuevo", "max"))
                    .reset_index(drop=True))
            prev["% OFF"] = ((1 - prev["precio"] / prev["tachado_nuevo"]) * 100).round(0)
            st.dataframe(prev, hide_index=True, width="stretch", height=min(40 + 35 * len(prev), 380),
                         column_config={"producto": st.column_config.TextColumn("Producto", width="large"),
                                        "precio": st.column_config.NumberColumn("Precio (no cambia)", format="$ %.0f"),
                                        "tachado_actual": st.column_config.NumberColumn("Tachado actual", format="$ %.0f"),
                                        "tachado_nuevo": st.column_config.NumberColumn("Tachado nuevo", format="$ %.0f"),
                                        "% OFF": st.column_config.NumberColumn(format="%.0f%%")})

        n_prod = aplica["product_id"].nunique()
        if ejecutar_ui("💲 Aplicar precio tachado", n_prod, "tach",
                       f"Confirmo cambiar el precio tachado de {n_prod} producto(s) ({len(aplica)} variantes)"):
            tit = P.set_index("product_id")["titulo"]
            f2 = lambda x: None if pd.isna(x) or x is None else f"{float(x):.2f}"  # noqa: E731
            filas = [{"id": pid, "label": tit.get(pid, pid),
                      "antes": [{"id": v["variant_id"], "compareAtPrice": f2(v["precio_tachado"])} for _, v in g.iterrows()],
                      "despues": [{"id": v["variant_id"], "compareAtPrice": f2(v["nuevo"])} for _, v in g.iterrows()]}
                     for pid, g in aplica.groupby("product_id")]
            desc = (f"{valor:.0f}% OFF" if modo_t == "% OFF" else f"${valor:,.0f}" if modo_t == "Monto fijo"
                    else f"precio +{valor:.0f}%" if modo_t == "Precio de lista + %"
                    else "quitar" if modo_t == "Quitar tachado" else "desde Excel")
            ops.mostrar_resultado(ops.aplicar(tienda, "precios", filas,
                                              f"{nombre}: precio tachado {desc} en {len(filas)} productos",
                                              progress=progreso("Precio tachado…")))




# ================================================================ cargar precios por modelo-color (a todos sus SKU)
with t_pre:
    from meli.catalog import norm as _norm
    from meli.ui import caja_texto
    st.caption("Pegá desde Excel **modelo-color · precio** y opcional **· precio tachado**. El precio se aplica a "
               "**todos los SKU (talles)** de ese modelo-color. También acepta un SKU completo para cambiar un solo talle. "
               "Se puede deshacer desde **Historial**.")
    txt = caja_texto("Modelo-color · Precio · Precio tachado (opcional)", "pre_txt", "✅ Leer", height=160,
                     placeholder="K1342233W-KSA02\t89999\t129999\nP14313300000310SS25\t74999")
    c1, c2 = st.columns(2)
    sin_tach = c1.radio("Si no pego precio tachado", ["No tocar el tachado actual", "Quitar el tachado"],
                        key="pre_sintach", horizontal=True)
    tach_inval = c2.radio("Si el tachado queda menor o igual al precio",
                          ["Quitarlo (Shopify no lo mostraría)", "Dejarlo igual"], key="pre_inval", horizontal=True)

    lineas, malas = [], []
    for ln in txt.splitlines():
        if not ln.strip():
            continue
        partes = [x.strip() for x in (ln.split("\t") if "\t" in ln else ln.split(";"))]
        if len(partes) == 1:
            partes = ln.split()
        cod = partes[0].upper() if partes else ""
        precio = _num(partes[1]) if len(partes) > 1 else None
        tach = _num(partes[2]) if len(partes) > 2 and partes[2] else None
        if cod.lower() in ("modelo", "modelo-color", "modelo_color", "sku", "codigo", "código"):
            continue
        if not cod or not precio:
            malas.append(ln.strip())
            continue
        lineas.append({"codigo": cod, "precio": precio, "tachado": tach})
    if malas:
        st.warning(f"{len(malas)} línea(s) sin precio válido: " + " | ".join(malas[:10]))

    if lineas:
        tit = P.set_index("product_id")["titulo"]
        _sku_n = V["sku"].fillna("").map(lambda x: _norm(x) if x else "")
        _mc_n = V["sku"].fillna("").map(lambda x: _norm(strip_size(x) or "") if x else "")
        cambios, faltan = [], []
        for ln in lineas:
            n = _norm(ln["codigo"])
            vv = V[(_sku_n == n) | (_mc_n == n)]   # SKU completo exacto o modelo-color exacto
            if vv.empty:   # sin SKU que coincida: buscar el producto por código / handle y aplicar a todas sus variantes
                hit, _ = _match_codigos(P, ln["codigo"])
                vv = V[V["product_id"].isin(hit["product_id"])]
            if vv.empty:
                faltan.append(ln["codigo"])
                continue
            for _, v in vv.iterrows():
                if ln["tachado"] is not None:
                    nt = ln["tachado"]
                elif sin_tach.startswith("Quitar"):
                    nt = None
                else:
                    nt = v["precio_tachado"] if pd.notna(v["precio_tachado"]) else None
                if nt is not None and nt <= ln["precio"] and tach_inval.startswith("Quitarlo"):
                    nt = None
                cambios.append({"codigo": ln["codigo"], "product_id": v["product_id"], "variant_id": v["variant_id"],
                                "producto": tit.get(v["product_id"], ""), "sku": v["sku"], "talle": v["variante"],
                                "precio_actual": v["precio"], "precio_nuevo": ln["precio"],
                                "tachado_actual": v["precio_tachado"] if pd.notna(v["precio_tachado"]) else None,
                                "tachado_nuevo": nt})
        if faltan:
            st.warning(f"No encontré {len(faltan)}: " + ", ".join(faltan[:30]))
        cd = pd.DataFrame(cambios)
        if not cd.empty:
            cd = cd.drop_duplicates("variant_id", keep="last")
            for c_ in ("precio_actual", "precio_nuevo", "tachado_actual", "tachado_nuevo"):
                cd[c_] = pd.to_numeric(cd[c_], errors="coerce")
            mismo = lambda a, b: (a.fillna(-1).round(2) == b.fillna(-1).round(2))  # noqa: E731
            cd = cd[~(mismo(cd["precio_actual"], cd["precio_nuevo"]) & mismo(cd["tachado_actual"], cd["tachado_nuevo"]))]
        if cd.empty:
            st.info("No hay cambios: los precios ya son esos.")
        else:
            cd["var_%"] = ((cd["precio_nuevo"] / cd["precio_actual"] - 1) * 100).round(1)
            res_ = (cd.groupby(["codigo", "producto"], sort=False)
                    .agg(talles=("variant_id", "count"), precio_actual=("precio_actual", "max"),
                         precio_nuevo=("precio_nuevo", "max"), tachado_actual=("tachado_actual", "max"),
                         tachado_nuevo=("tachado_nuevo", "max"), var=("var_%", "max")).reset_index())
            m1, m2, m3 = st.columns(3)
            m1.metric("Modelo-color", cd["codigo"].nunique())
            m2.metric("SKU (talles) que cambian", len(cd))
            grandes = int((cd["var_%"].abs() > 50).sum())
            m3.metric("⚠️ Cambios > 50%", grandes)
            if grandes:
                st.warning(f"{grandes} SKU cambian más de 50% de precio: revisá que no falte o sobre un cero.")
            st.dataframe(res_, hide_index=True, width="stretch", height=min(40 + 36 * len(res_), 420),
                         column_config={"codigo": "Modelo-color", "producto": st.column_config.TextColumn("Producto", width="large"),
                                        "precio_actual": st.column_config.NumberColumn("Precio actual", format="$ %.0f"),
                                        "precio_nuevo": st.column_config.NumberColumn("Precio nuevo", format="$ %.0f"),
                                        "tachado_actual": st.column_config.NumberColumn("Tachado actual", format="$ %.0f"),
                                        "tachado_nuevo": st.column_config.NumberColumn("Tachado nuevo", format="$ %.0f"),
                                        "var": st.column_config.NumberColumn("Var. %", format="%.1f%%")})
            with st.expander("Ver detalle por SKU"):
                st.dataframe(cd.drop(columns=["product_id", "variant_id"]), hide_index=True, width="stretch")
            n_prod = cd["product_id"].nunique()
            if ejecutar_ui("💰 Aplicar precios", len(cd), "pre",
                           f"Confirmo cambiar el precio de {len(cd)} SKU ({cd['codigo'].nunique()} modelo-color)"):
                f2 = lambda x: None if x is None or pd.isna(x) else f"{float(x):.2f}"  # noqa: E731
                filas = [{"id": pid, "label": g["producto"].iloc[0],
                          "antes": [{"id": r["variant_id"], "price": f2(r["precio_actual"]),
                                     "compareAtPrice": f2(r["tachado_actual"])} for _, r in g.iterrows()],
                          "despues": [{"id": r["variant_id"], "price": f2(r["precio_nuevo"]),
                                       "compareAtPrice": f2(r["tachado_nuevo"])} for _, r in g.iterrows()]}
                         for pid, g in cd.groupby("product_id")]
                ops.mostrar_resultado(ops.aplicar(tienda, "precios", filas,
                                                  f"{nombre}: cargar precios de {cd['codigo'].nunique()} modelo-color "
                                                  f"({len(cd)} SKU)", progress=progreso("Cargando precios…")))
