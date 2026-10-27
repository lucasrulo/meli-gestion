import re

import pandas as pd
import streamlit as st

from meli import azure_fotos as az
from meli import contenido as ct
from meli import shop_ops as ops
from meli.config import secret
from meli.excel import to_xlsx
from meli.shop_ui import ESTADOS, _match_codigos, cargar, ejecutar_ui, pick_store, progreso, selector
from meli.shopify import ShopifyClient, ShopifyError, stores
from meli.theme import hero

hero("Imágenes Shopify", "Fotos de productos desde Azure, texto alternativo de productos y de banners/archivos de la tienda.",
     "SHOPIFY · IMÁGENES")
tienda = pick_store()
nombre = stores()[tienda]["nombre"]
P, V, M, MF = cargar(tienda)
api_key = secret("ANTHROPIC_API_KEY")

t_fot, t_alt, t_ban = st.tabs(["📸 Fotos de productos (Azure)", "🏷️ Alt de productos", "🖼️ Alt de banners y archivos"])


def _aplicar_alt(df: pd.DataFrame, desc: str, id_col: str = "media_id", label_col: str = "titulo"):
    filas = [{"id": r[id_col], "label": r[label_col], "antes": r["alt"] or "", "despues": r["nuevo_alt"]}
             for _, r in df.iterrows() if str(r["nuevo_alt"]).strip()]
    ops.mostrar_resultado(ops.aplicar(tienda, "alt", filas, desc, progress=progreso("Texto alternativo…")))


# ================================================================ 1. fotos de productos (Azure)
def _tabla_fotos(df: pd.DataFrame, key: str, extra: list[str] | None = None, check: bool = True) -> pd.DataFrame:
    """Tabla con foto de Azure vs Shopify; devuelve los tildados."""
    v = df.copy()
    v["estado"] = v["estado"].map(lambda x: ESTADOS.get(x, x))
    v["foto"] = v["foto"].fillna("")
    v["vista_azure"] = v["urls"].map(lambda u: u[0] if u else None)
    v.insert(0, "✔", check)
    cols = ["✔", "vista_azure", "foto", "titulo", "estado", "n_shopify", "n_azure"] + (extra or []) + ["codigo_azure"]
    ed = st.data_editor(v[cols + ["product_id"]], hide_index=True, width="stretch", row_height=56,
                        height=min(40 + 58 * len(v), 460), key=f"{key}_{len(v)}_{hash(tuple(v['product_id']))}",
                        disabled=[c for c in cols if c != "✔"], column_order=cols,
                        column_config={"vista_azure": st.column_config.ImageColumn("Azure", width="small"),
                                       "foto": st.column_config.ImageColumn("Shopify", width="small"),
                                       "titulo": st.column_config.TextColumn("Producto", width="large"),
                                       "n_shopify": "Fotos Shopify", "n_azure": "Fotos Azure",
                                       "azure_txt": "Cambió en Azure", "codigo_azure": "Código en Azure",
                                       "codigos": "Códigos buscados"})
    return df[df["product_id"].isin(ed.loc[ed["✔"], "product_id"])]


def _cargar(filas_df: pd.DataFrame, reemplazar: bool, carpeta: str, solo_faltantes: bool = False) -> None:
    """Carga las fotos de Azure. Reemplazar: primero carga las nuevas y recién después quita las viejas
    (si la carga falla, el producto queda con sus fotos actuales)."""
    mm = M.groupby("product_id")["media_id"].apply(list).to_dict()
    urls_sh = M.groupby("product_id")["url"].apply(
        lambda s_: {str(u).split("?")[0].rsplit("/", 1)[-1].lower() for u in s_}).to_dict()
    filas = []
    for _, r in filas_df.iterrows():
        urls = r["urls"]
        if solo_faltantes:
            ya = urls_sh.get(r["product_id"], set())
            urls = [u for u in urls if u.rsplit("/", 1)[-1].lower() not in ya]
        if urls:
            filas.append({"id": r["product_id"], "label": r["titulo"], "alt": r["titulo"],
                          "antes": mm.get(r["product_id"], []), "despues": urls})
    if not filas:
        st.info("No hay fotos nuevas para cargar.")
        return
    res = ops.aplicar(tienda, "fotos_add", filas, f"{nombre}: {'reemplazar' if reemplazar else 'cargar'} fotos de "
                      f"Azure/{carpeta} en {len(filas)} productos", {"carpeta": carpeta}, progress=progreso("Cargando fotos…"))
    ops.mostrar_resultado(res)
    if reemplazar:
        quitar = [{"id": f["id"], "label": f["label"], "antes": None, "despues": f["antes"]}
                  for f in filas if f.get("ok") and f["antes"]]
        if quitar:
            ops.mostrar_resultado(ops.aplicar(tienda, "fotos_remove", quitar,
                                              f"{nombre}: quitar fotos viejas de {len(quitar)} productos",
                                              reversible=False, progress=progreso("Quitando fotos viejas…")))
    st.caption("Shopify descarga las imágenes en segundo plano: pueden tardar 1–2 minutos en verse. "
               "Tocá **🔄 Releer catálogo** para ver los números actualizados.")


with t_fot:
    st.caption(f"Fuente: `{az.base_url()}` · se matchea por código de artículo / modelo-color del SKU (y handle).")
    try:
        carps = az.carpetas()
    except Exception as e:  # noqa: BLE001
        st.error(f"No pude leer Azure: {e}")
        carps = []
    if carps:
        sug = next((c for c in carps if c.lower().replace(" ", "") == nombre.lower().replace(" ", "")), carps[0])
        carpeta = st.selectbox("Carpeta de Azure (marca)", carps, index=carps.index(sug), key="az_carp")
        with st.spinner("Listando fotos de Azure…"):
            F = az.fotos(carpeta)
        mt = az.matchear(P, F, M)
        sin_sh = mt[mt["n_shopify"] == 0]
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Sin fotos en Shopify", len(sin_sh))
        m2.metric("…y con fotos en Azure", int((sin_sh["n_azure"] > 0).sum()))
        m3.metric("Cambiaron en Azure", int(mt["cambio_azure"].sum()),
                  help="Productos cuyas fotos en Azure son más nuevas que las cargadas en Shopify.")
        m4.metric("Sin fotos en Azure", int((mt["n_azure"] == 0).sum()))

        accion = st.segmented_control("¿Qué querés hacer?", ["🕳️ Sin fotos en Shopify", "🔄 Actualizar / reemplazar",
                                                            "➕ Completar faltantes"],
                                      default="🕳️ Sin fotos en Shopify", key="az_acc") or "🕳️ Sin fotos en Shopify"

        if accion == "🕳️ Sin fotos en Shopify":
            v = sin_sh.copy()
            v["en_azure"] = v["n_azure"].map(lambda n: f"✅ Sí ({n})" if n else "❌ No")
            f1, f2 = st.columns([1.4, 1])
            ver = f1.radio("Mostrar", ["Todos", "Con fotos en Azure (se pueden cargar)", "Sin fotos en Azure"],
                           horizontal=True, key="az_sin_ver")
            solo_act = f2.toggle("Solo activos / no listados", value=False, key="az_sin_act")
            if ver.startswith("Con"):
                v = v[v["n_azure"] > 0]
            elif ver.startswith("Sin"):
                v = v[v["n_azure"] == 0]
            if solo_act:
                v = v[v["estado"].isin(["ACTIVE", "UNLISTED"])]
            st.caption(f"{len(v)} producto(s). Los que no están en Azure muestran qué códigos se buscaron.")
            if not v.empty:
                elegidos = _tabla_fotos(v, "az_sin", ["en_azure", "codigos"], check=True)
                xl = v.assign(estado=v["estado"].map(lambda x: ESTADOS.get(x, x).split(" ", 1)[-1]))[
                    ["titulo", "estado", "en_azure", "n_azure", "codigo_azure", "skus", "codigos"]]
                c1, c2 = st.columns([1, 2])
                c1.download_button("⬇️ Descargar Excel", to_xlsx(xl), f"{nombre}_sin_fotos.xlsx")
                cargables = elegidos[elegidos["n_azure"] > 0]
                with c2:
                    if ejecutar_ui("🖼️ Cargar fotos de Azure", len(cargables), "az_sin",
                                   f"Cargar fotos en {len(cargables)} producto(s) que tienen fotos en Azure"):
                        _cargar(cargables, False, carpeta)

        elif accion == "🔄 Actualizar / reemplazar":
            st.caption("Borra las fotos que tiene Shopify y carga las de Azure (primero carga las nuevas; si algo falla, "
                       "el producto conserva sus fotos). Las fotos borradas no se pueden recuperar con Deshacer.")
            como = st.radio("Elegir productos", ["Pegar códigos", "Los que cambiaron en Azure"], horizontal=True,
                            key="az_upd_como")
            if como == "Pegar códigos":
                txt = st.text_area("Códigos de artículo, modelo-color o SKUs (uno por línea)", key="az_upd_cod", height=110)
                selp, faltan = _match_codigos(P, txt)
                if faltan:
                    st.warning(f"No encontré en Shopify {len(faltan)}: " + ", ".join(faltan[:30]))
                v = mt[mt["product_id"].isin(selp["product_id"])]
            else:
                v = mt[mt["cambio_azure"]]
            sin_az = v[v["n_azure"] == 0]
            if len(sin_az):
                st.warning(f"{len(sin_az)} no tienen fotos en Azure y se omiten: " + ", ".join(sin_az["titulo"].head(10)))
            v = v[v["n_azure"] > 0].copy()
            v["azure_txt"] = v["azure_mod"].map(lambda d: d.strftime("%d/%m/%Y") if pd.notna(d) else "")
            if v.empty:
                st.caption("Sin productos para actualizar.")
            else:
                elegidos = _tabla_fotos(v, "az_upd", ["azure_txt"])
                if ejecutar_ui("🔄 Reemplazar fotos", len(elegidos), "az_upd",
                               f"Confirmo BORRAR las fotos actuales de {len(elegidos)} producto(s) y cargar las de Azure"):
                    _cargar(elegidos, True, carpeta)

        else:
            v = mt[mt["n_azure"] > mt["n_shopify"]]
            st.caption(f"{len(v)} producto(s) tienen más fotos en Azure que en Shopify. Se agregan solo las que faltan "
                       "(por nombre de archivo), sin tocar las actuales.")
            if not v.empty:
                elegidos = _tabla_fotos(v, "az_fal")
                if ejecutar_ui("➕ Agregar fotos faltantes", len(elegidos), "az_fal"):
                    _cargar(elegidos, False, carpeta, solo_faltantes=True)


# ================================================================ 2. alt de productos
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


# ================================================================ 3. alt de banners y archivos
@st.cache_data(ttl=600, show_spinner=False)
def _archivos(key: str, nonce) -> pd.DataFrame:
    q = """query($c: String) { files(first: 250, after: $c, query: "media_type:IMAGE") {
             pageInfo { hasNextPage endCursor }
             nodes { ... on MediaImage { id alt createdAt image { url width height } } } } }"""
    cli, rows, cur = ShopifyClient(key), [], None
    while True:
        d = cli.gql(q, {"c": cur})["files"]
        for n in d["nodes"]:
            if n.get("id"):
                img = n.get("image") or {}
                url = img.get("url") or ""
                rows.append({"file_id": n["id"], "alt": n.get("alt") or "", "url": url,
                             "archivo": url.split("?")[0].rsplit("/", 1)[-1], "creado": (n.get("createdAt") or "")[:10],
                             "medida": f"{img.get('width')}×{img.get('height')}" if img.get("width") else ""})
        if not d["pageInfo"]["hasNextPage"] or len(rows) > 30000:
            break
        cur = d["pageInfo"]["endCursor"]
    return pd.DataFrame(rows, columns=["file_id", "alt", "url", "archivo", "creado", "medida"])


def _alt_archivo(archivo: str) -> str:
    """Alt sin IA a partir del nombre del archivo: 'banner-hot-sale_2026_1920x600_ab12cd.jpg' → 'Kappa - Banner hot sale 2026'."""
    t = archivo.rsplit(".", 1)[0]
    t = re.sub(r"_[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$", "", t, flags=re.I)  # sufijo uuid de Shopify
    t = re.sub(r"[-_]+", " ", t)
    t = re.sub(r"\b\d{3,4}\s?x\s?\d{3,4}\b", " ", t, flags=re.I).strip()            # medidas (1920x600)
    t = re.sub(r"\s+", " ", t)
    return (f"{nombre} - {t[:1].upper()}{t[1:]}" if t else nombre)[:125]


with t_ban:
    st.caption("Imágenes subidas a **Contenido → Archivos** que no son fotos de productos: banners, sliders, íconos, "
               "imágenes de colecciones y del theme. El alt que pongas acá es el que muestra el theme.")
    nkb = f"files_nonce_{tienda}"
    c0, c1 = st.columns([4, 1], vertical_alignment="center")
    if c1.button("🔄 Releer archivos", key="ban_ref", width="stretch"):
        st.session_state[nkb] = st.session_state.get(nkb, 0) + 1
    try:
        with st.spinner("Leyendo archivos de la tienda…"):
            A = _archivos(tienda, st.session_state.get(nkb, 0))
    except ShopifyError as e:
        st.error(str(e))
        A = pd.DataFrame(columns=["file_id", "alt", "url", "archivo", "creado", "medida"])
    A = A[~A["file_id"].isin(set(M["media_id"]))]   # saca las fotos de productos
    sin = A[A["alt"].str.strip() == ""]
    c0.caption(f"{len(A)} imágenes de la tienda · **{len(sin)} sin texto alternativo**")
    f1, f2 = st.columns([1, 2])
    solo_sin = f1.toggle("Solo sin alt", value=True, key="ban_sin")
    q = f2.text_input("Buscar por nombre de archivo", key="ban_q", placeholder="banner, slider, hot-sale…")
    v = sin if solo_sin else A
    if q:
        v = v[v["archivo"].str.contains(q, case=False, regex=False)]
    v = v.sort_values("creado", ascending=False).head(500)
    kb = f"ban_gen_{tienda}"
    modelo = secret("ANTHROPIC_MODEL_ALT", "claude-haiku-4-5")
    b1, b2, b3 = st.columns([1, 1, 2], vertical_alignment="center")
    if b1.button("💡 Desde el nombre (gratis)", key="ban_r", width="stretch", disabled=v.empty):
        st.session_state[kb] = {r["file_id"]: _alt_archivo(r["archivo"]) for _, r in v.iterrows()}
    if b2.button("✨ Con IA (mira la imagen)", key="ban_ia", width="stretch", disabled=v.empty or not api_key,
                 help=None if api_key else "Cargá ANTHROPIC_API_KEY en los Secrets."):
        from concurrent.futures import ThreadPoolExecutor, as_completed
        bar, gasto, gen = progreso("IA describiendo imágenes…"), 0.0, {}
        with ThreadPoolExecutor(max_workers=4) as ex:
            futs = {ex.submit(ct.ai_alt, api_key, modelo, r["url"], f"Imagen de la tienda {nombre}: {r['archivo']}"):
                    r["file_id"] for _, r in v.iterrows()}
            for i, f in enumerate(as_completed(futs), 1):
                try:
                    txt, c = f.result()
                    gen[futs[f]], gasto = txt, gasto + c
                except Exception as e:  # noqa: BLE001
                    st.warning(str(e)[:200])
                bar(i / len(futs))
        st.session_state[kb] = gen
        st.toast(f"Listo · US$ {gasto:.3f}")
    b3.caption(f"{len(v)} imagen(es) en la lista · IA ~US$ {len(v) * 0.002:.2f}")
    if not v.empty:
        gen = st.session_state.get(kb, {})
        v = v.assign(nuevo_alt=v["file_id"].map(gen).fillna(v["alt"]).astype(str))
        ed = st.data_editor(v[["url", "archivo", "medida", "alt", "nuevo_alt", "file_id"]], hide_index=True, width="stretch",
                            row_height=60, height=min(40 + 62 * len(v), 480), key=f"ban_ed_{len(v)}_{len(gen)}",
                            column_order=["url", "archivo", "medida", "alt", "nuevo_alt"],
                            disabled=["url", "archivo", "medida", "alt"],
                            column_config={"url": st.column_config.ImageColumn("Imagen", width="small"),
                                           "archivo": st.column_config.TextColumn("Archivo", width="medium"),
                                           "alt": "Alt actual",
                                           "nuevo_alt": st.column_config.TextColumn("✏️ Alt nuevo", width="large", max_chars=125)})
        camb = ed[ed["nuevo_alt"].fillna("") != ed["alt"].fillna("")]
        if ejecutar_ui("🖼️ Guardar texto alternativo", len(camb), "ban", f"Confirmo actualizar {len(camb)} imagen(es)"):
            _aplicar_alt(camb, f"{nombre}: alt de {len(camb)} banners/archivos", "file_id", "archivo")
            st.session_state.pop(kb, None)
            st.session_state[nkb] = st.session_state.get(nkb, 0) + 1
