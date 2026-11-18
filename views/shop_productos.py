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

hero("Productos y stock", "Estado, canales, talles con EAN y stock, y metacampos — en masa y con deshacer.", "SHOPIFY · PRODUCTOS")
tienda = pick_store()
nombre = stores()[tienda]["nombre"]
P, V, M, MF = cargar(tienda)
api_key = secret("ANTHROPIC_API_KEY")

t_est, t_tal, t_meta = st.tabs(["🚦 Estado y canales", "📏 Talles, EAN y stock", "🧩 Metacampos"])


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



# ================================================================ talles nuevos: SKU + EAN + stock
with t_tal:
    from meli import historial as _hist
    from meli import shop_talles as stl
    from meli.ui import caja_texto
    st.caption("Pegá 3 columnas desde Excel: **SKU · EAN · Stock**. Cada SKU se asocia a su producto por modelo-color "
               "(SKU sin el talle). Si el talle no existe **se crea** (con el precio y tachado del producto); si ya existe "
               "se actualizan EAN y stock. Productos sin talles (variante única) pasan a tener la opción **Talle**.")
    txt = caja_texto("SKU · EAN · Stock", "tal_txt", "✅ Leer", height=160,
                     placeholder="K1342233W-KSA02-40\t7791234567890\t5\nK1342233W-KSA02-41\t7791234567891\t3")
    df_in, malas = stl.parse(txt)
    if malas:
        st.warning(f"{len(malas)} línea(s) que no pude leer: " + " | ".join(malas[:10]))
    if not df_in.empty:
        plan = stl.asociar(df_in, P, V)
        c1, c2, c3 = st.columns(3)
        c1.metric("🆕 Talles a crear", int((plan["accion"] == "🆕 Crear talle").sum()))
        c2.metric("✏️ A actualizar", int((plan["accion"] == "✏️ Actualizar").sum()))
        c3.metric("⚠️ Con error", int((plan["accion"] == "⚠️ Error").sum()))
        st.dataframe(plan[["accion", "producto", "sku", "talle", "ean", "stock", "detalle"]].sort_values(["accion", "producto", "sku"]),
                     hide_index=True, width="stretch", height=min(40 + 36 * len(plan), 460),
                     column_config={"accion": "Acción", "producto": st.column_config.TextColumn("Producto", width="large"),
                                    "ean": "EAN", "detalle": "Detalle"})
        c1, c2 = st.columns(2)
        try:
            locs = stl.ubicaciones(tienda)
        except ShopifyError as e:
            locs = []
            st.error(f"No pude leer las ubicaciones de stock: {e}")
            st.info("La app necesita los permisos **read_locations** y **write_inventory** (Dev Dashboard → nueva versión "
                    "con esos scopes → Release → Configuración → Cuentas y tiendas → Conectar tienda de nuevo).")
        loc = c1.selectbox("Ubicación del stock", [x["id"] for x in locs], key="tal_loc",
                           format_func=lambda i: next(x["name"] for x in locs if x["id"] == i)) if locs else None
        opcion = c2.text_input("Nombre de la opción (para productos sin talles)", "Talle", key="tal_opt")
        validas = plan[plan["product_id"].notna()]
        if loc and ejecutar_ui("📏 Cargar talles y stock", len(validas), "tal",
                               f"Confirmo cargar {len(validas)} SKU en {validas['product_id'].nunique()} productos"):
            res = stl.aplicar(tienda, validas, loc, opcion or "Talle", progress=progreso("Cargando talles…"))
            ok = int(res["ok"].sum()) if not res.empty else 0
            (st.success if ok == len(res) else st.warning)(f"✅ {ok} OK" + (f" · ❌ {len(res) - ok} con error"
                                                                          if ok < len(res) else ""))
            if ok < len(res):
                st.dataframe(res.loc[~res["ok"], ["producto", "sku", "talle", "error"]], hide_index=True, width="stretch")
            _hist.registrar("Shopify", tienda, "talles_stock", f"{nombre}: cargar {ok} SKU (talles, EAN y stock)",
                            [{"id": r["variant_id"] or r["product_id"], "label": f"{r['producto']} · {r['sku']}",
                              "antes": None, "despues": {"ean": r["ean"], "stock": r["stock"], "accion": r["accion"]},
                              "ok": bool(r["ok"]), "error": r["error"]} for r in res.to_dict("records")],
                            {}, False)
            from meli.shop_bulk import invalidar as _inv
            _inv(tienda)
            st.download_button("⬇️ Resultado en Excel", to_xlsx(res[["accion", "producto", "sku", "talle", "ean", "stock",
                                                                    "ok", "error"]]), f"talles_{tienda}.xlsx")
