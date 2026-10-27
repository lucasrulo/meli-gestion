"""Acciones masivas de Shopify con registro en el historial y su inversa (para deshacer).

Cada acción recibe "filas": [{"id": <gid>, "label": <texto>, "antes": ..., "despues": ...}]
"""
import pandas as pd
import streamlit as st

from . import historial
from .shop_bulk import ejecutar, invalidar
from .shopify import ShopifyClient

COLL_VERSION = "2026-04"  # colecciones manuales/automáticas con el modelo clásico (2026-07 cambia el modelo)

M_STATUS = """mutation($p: ProductUpdateInput!) { productUpdate(product: $p) { product { id status } userErrors { field message } } }"""
M_SEO = """mutation($p: ProductUpdateInput!) { productUpdate(product: $p) { product { id } userErrors { field message } } }"""
M_TAGS_ADD = """mutation($id: ID!, $tags: [String!]!) { tagsAdd(id: $id, tags: $tags) { node { id } userErrors { field message } } }"""
M_TAGS_REM = """mutation($id: ID!, $tags: [String!]!) { tagsRemove(id: $id, tags: $tags) { node { id } userErrors { field message } } }"""
M_PUBLISH = """mutation($id: ID!, $input: [PublicationInput!]!) { publishablePublish(id: $id, input: $input) {
                 userErrors { field message } } }"""
M_UNPUBLISH = """mutation($id: ID!, $input: [PublicationInput!]!) { publishableUnpublish(id: $id, input: $input) {
                   userErrors { field message } } }"""
M_ALT = """mutation($files: [FileUpdateInput!]!) { fileUpdate(files: $files) { files { id } userErrors { field message } } }"""
M_MEDIA_ADD = """mutation($p: ProductUpdateInput!, $m: [CreateMediaInput!]) { productUpdate(product: $p, media: $m) {
                   product { id media(first: 250) { nodes { id } } } userErrors { field message } } }"""
M_META_SET = """mutation($m: [MetafieldsSetInput!]!) { metafieldsSet(metafields: $m) { metafields { id } userErrors { field message } } }"""
M_META_DEL = """mutation($m: [MetafieldIdentifierInput!]!) { metafieldsDelete(metafields: $m) { deletedMetafields { key }
                  userErrors { field message } } }"""
M_REDIR_ADD = """mutation($r: UrlRedirectInput!) { urlRedirectCreate(urlRedirect: $r) { urlRedirect { id path target }
                   userErrors { field message } } }"""
M_REDIR_DEL = """mutation($id: ID!) { urlRedirectDelete(id: $id) { deletedUrlRedirectId userErrors { field message } } }"""
M_PRECIOS = """mutation($pid: ID!, $v: [ProductVariantsBulkInput!]!) { productVariantsBulkUpdate(productId: $pid, variants: $v) {
                 userErrors { field message } } }"""
M_COLL_ADD = """mutation($id: ID!, $ids: [ID!]!) { collectionAddProductsV2(id: $id, productIds: $ids) { job { id }
                  userErrors { field message } } }"""
M_COLL_REM = """mutation($id: ID!, $ids: [ID!]!) { collectionRemoveProducts(id: $id, productIds: $ids) { job { id }
                  userErrors { field message } } }"""

NOMBRES = {
    "estado": "Cambio de estado", "tags_set": "Reemplazar tags", "tags_add": "Agregar tags", "tags_remove": "Quitar tags",
    "publicar": "Publicar en canales", "despublicar": "Despublicar de canales", "seo": "SEO title / meta",
    "alt": "Texto alternativo de fotos", "fotos_add": "Agregar fotos", "fotos_remove": "Quitar fotos",
    "metacampos": "Metacampos", "redirect_add": "Crear redirecciones", "redirect_remove": "Borrar redirecciones",
    "precios": "Precios Shopify", "coleccion_add": "Agregar a colección", "coleccion_remove": "Quitar de colección",
    "contenido": "Descripción/SEO Shopify", "coleccion_seo": "SEO de colecciones", "meta_owner": "SEO de páginas/blog",
    "imagen_ref_add": "Imagen compartida a productos", "imagen_ref_remove": "Quitar imagen compartida", "meli_descripcion": "Descripción MeLi", "meli_precio": "Precio MeLi", "meli_fotos": "Imagen en publicaciones MeLi",
}


# ---------------------------------------------------------------- variables por acción
M_COLL_SEO = """mutation($i: CollectionInput!) { collectionUpdate(input: $i) { collection { id } userErrors { field message } } }"""


def _vars(accion: str, f: dict, meta: dict):
    d = f["despues"]
    if accion in ("imagen_ref_add", "imagen_ref_remove"):   # misma imagen (Archivo) en muchos productos
        campo = "referencesToAdd" if accion == "imagen_ref_add" else "referencesToRemove"
        return M_ALT, {"files": [{"id": meta["file_id"], campo: [f["id"]]}]}
    if accion == "coleccion_seo":
        return M_COLL_SEO, {"i": {"id": f["id"], "seo": {"title": d.get("title", ""), "description": d.get("description", "")}}}
    if accion == "meta_owner":   # metacampo de cualquier recurso (páginas, artículos): f["meta"] = {namespace, key, type}
        m = f["meta"]
        if d in (None, ""):
            return M_META_DEL, {"m": [{"ownerId": f["id"], "namespace": m["namespace"], "key": m["key"]}]}
        return M_META_SET, {"m": [{"ownerId": f["id"], "namespace": m["namespace"], "key": m["key"],
                                   "type": m.get("type", "single_line_text_field"), "value": str(d)}]}
    if accion == "estado":
        return M_STATUS, {"p": {"id": f["id"], "status": d}}
    if accion == "tags_set":
        return M_STATUS.replace("status }", "tags }"), {"p": {"id": f["id"], "tags": list(d)}}
    if accion == "tags_add":
        return M_TAGS_ADD, {"id": f["id"], "tags": list(d)}
    if accion == "tags_remove":
        return M_TAGS_REM, {"id": f["id"], "tags": list(d)}
    if accion in ("publicar", "despublicar"):
        return (M_PUBLISH if accion == "publicar" else M_UNPUBLISH), \
            {"id": f["id"], "input": [{"publicationId": p} for p in d]}
    if accion == "seo":
        return M_SEO, {"p": {"id": f["id"], "seo": {"title": d.get("title", ""), "description": d.get("description", "")}}}
    if accion == "contenido":
        p = {"id": f["id"]}
        if "descriptionHtml" in d:
            p["descriptionHtml"] = d["descriptionHtml"]
        if "seo" in d:
            p["seo"] = d["seo"]
        return M_SEO, {"p": p}
    if accion == "alt":
        return M_ALT, {"files": [{"id": f["id"], "alt": d or ""}]}
    if accion == "fotos_add":
        return M_MEDIA_ADD, {"p": {"id": f["id"]},
                             "m": [{"originalSource": u, "mediaContentType": "IMAGE", "alt": f.get("alt") or ""} for u in d]}
    if accion == "fotos_remove":  # f["id"] = producto, despues = media ids a quitar
        return M_ALT, {"files": [{"id": m, "referencesToRemove": [f["id"]]} for m in d]}
    if accion == "metacampos":
        ns, key, tipo = meta["namespace"], meta["key"], meta["type"]
        if d in (None, ""):
            return M_META_DEL, {"m": [{"ownerId": f["id"], "namespace": ns, "key": key}]}
        return M_META_SET, {"m": [{"ownerId": f["id"], "namespace": ns, "key": key, "type": tipo, "value": str(d)}]}
    if accion == "redirect_add":
        return M_REDIR_ADD, {"r": {"path": d["path"], "target": d["target"]}}
    if accion == "redirect_remove":
        return M_REDIR_DEL, {"id": f["id"]}
    if accion == "precios":  # f["id"] = producto, despues = [{"id", "price", "compareAtPrice"}]
        return M_PRECIOS, {"pid": f["id"], "v": [{k: v for k, v in x.items()} for x in d]}
    raise ValueError(f"Acción desconocida: {accion}")


def _post(accion: str, f: dict, data: dict) -> None:
    """Completa la fila con lo que devolvió Shopify (ids creados) para poder deshacer."""
    if accion == "fotos_add":
        nodes = ((((data.get("productUpdate") or {}).get("product") or {}).get("media") or {}).get("nodes")) or []
        antes = set(f.get("antes") or [])
        f["creados"] = [n["id"] for n in nodes if n["id"] not in antes]
    if accion == "redirect_add":
        f["creado_id"] = (((data.get("urlRedirectCreate") or {}).get("urlRedirect")) or {}).get("id")


# ---------------------------------------------------------------- aplicar
def aplicar(tienda: str, accion: str, filas: list[dict], descripcion: str, meta: dict | None = None,
            reversible: bool = True, deshace: str | None = None, progress=None) -> pd.DataFrame:
    meta = meta or {}
    if accion in ("coleccion_add", "coleccion_remove"):
        return _coleccion(tienda, accion, filas, descripcion, meta, deshace, progress)
    pares = [_vars(accion, f, meta) for f in filas]
    grupos: dict[str, list[int]] = {}
    for i, (mut, _) in enumerate(pares):
        grupos.setdefault(mut, []).append(i)
    res: list[dict | None] = [None] * len(filas)
    hechos = 0
    for mut, idxs in grupos.items():
        def prog(p, base=hechos, n=len(idxs)):
            if progress:
                progress((base + p * n) / len(filas))
        out = ejecutar(tienda, mut, [pares[i][1] for i in idxs], progress=prog,
                       version=COLL_VERSION if accion == "coleccion_seo" else None)
        for i, r in zip(idxs, out):
            res[i] = r
        hechos += len(idxs)
    for f, r in zip(filas, res):
        f["ok"], f["error"] = bool(r["ok"]), r["error"]
        if r["ok"]:
            _post(accion, f, r["data"])
    op = historial.registrar("Shopify", tienda, accion, descripcion, filas, meta, reversible, deshace)
    invalidar(tienda)
    df = pd.DataFrame([{"producto": f.get("label") or f["id"], "resultado": "OK" if f["ok"] else "ERROR",
                        "error": f["error"]} for f in filas])
    df.attrs["op_id"] = op
    return df


def _coleccion(tienda, accion, filas, descripcion, meta, deshace, progress):
    cli = ShopifyClient(tienda)
    mut = M_COLL_ADD if accion == "coleccion_add" else M_COLL_REM
    for i in range(0, len(filas), 250):
        lote = filas[i:i + 250]
        try:
            data = cli.gql(mut, {"id": meta["collection_id"], "ids": [f["id"] for f in lote]}, version=COLL_VERSION)
            err = "; ".join(e["message"] for e in (list(data.values())[0] or {}).get("userErrors") or [])
        except Exception as e:  # noqa: BLE001
            err = str(e)
        for f in lote:
            f["ok"], f["error"] = not err, err
        if progress:
            progress(min((i + 250) / len(filas), 1.0))
    op = historial.registrar("Shopify", tienda, accion, descripcion, filas, meta, True, deshace)
    invalidar(tienda)
    df = pd.DataFrame([{"producto": f.get("label") or f["id"], "resultado": "OK" if f["ok"] else "ERROR",
                        "error": f["error"]} for f in filas])
    df.attrs["op_id"] = op
    return df


# ---------------------------------------------------------------- deshacer
def inversa(entry: dict) -> tuple[str, list[dict], dict] | None:
    """Arma la operación que revierte `entry` (solo filas OK). None si no se puede."""
    acc, meta = entry["accion"], dict(entry.get("meta") or {})
    ok = [f for f in entry["filas"] if f.get("ok")]
    if not ok or not entry.get("reversible", True):
        return None
    sw = lambda f, **k: {**{x: f[x] for x in ("meta", "alt") if x in f}, "id": f["id"], "label": f.get("label"),  # noqa: E731
                         "antes": f["despues"], "despues": f["antes"], **k}
    if acc in ("estado", "tags_set", "seo", "coleccion_seo", "meta_owner", "alt", "metacampos", "contenido", "meli_descripcion", "meli_precio", "meli_fotos"):
        return acc, [sw(f) for f in ok], meta
    if acc == "precios":
        return acc, [sw(f) for f in ok], meta
    if acc in ("tags_add", "tags_remove"):
        otra = "tags_remove" if acc == "tags_add" else "tags_add"
        return otra, [{"id": f["id"], "label": f.get("label"), "antes": f["despues"], "despues": f["despues"]} for f in ok], meta
    if acc in ("publicar", "despublicar"):
        otra = "despublicar" if acc == "publicar" else "publicar"
        return otra, [{"id": f["id"], "label": f.get("label"), "antes": f["despues"], "despues": f["despues"]} for f in ok], meta
    if acc in ("coleccion_add", "coleccion_remove"):
        otra = "coleccion_remove" if acc == "coleccion_add" else "coleccion_add"
        return otra, [{"id": f["id"], "label": f.get("label"), "antes": None, "despues": None} for f in ok], meta
    if acc in ("imagen_ref_add", "imagen_ref_remove"):
        otra = "imagen_ref_remove" if acc == "imagen_ref_add" else "imagen_ref_add"
        return otra, [{"id": f["id"], "label": f.get("label"), "antes": None, "despues": None} for f in ok], meta
    if acc == "fotos_add":
        filas = [{"id": f["id"], "label": f.get("label"), "antes": None, "despues": f.get("creados") or []}
                 for f in ok if f.get("creados")]
        return ("fotos_remove", filas, meta) if filas else None
    if acc == "redirect_add":
        filas = [{"id": f["creado_id"], "label": f.get("label"), "antes": f["despues"], "despues": None}
                 for f in ok if f.get("creado_id")]
        return ("redirect_remove", filas, meta) if filas else None
    if acc == "redirect_remove":
        filas = [{"id": None, "label": f.get("label"), "antes": None, "despues": f["antes"]} for f in ok if f.get("antes")]
        return ("redirect_add", filas, meta) if filas else None
    return None


def deshacer(entry: dict, progress=None) -> pd.DataFrame | None:
    inv = inversa(entry)
    if not inv:
        return None
    acc, filas, meta = inv
    desc = f"Deshacer: {entry['descripcion']}"
    if acc.startswith("meli_"):
        return _deshacer_meli(entry, acc, filas, desc)
    return aplicar(entry["tienda"], acc, filas, desc, meta, reversible=False, deshace=entry["id"], progress=progress)


def _deshacer_meli(entry, acc, filas, desc):
    from .api import MeliClient
    from .auth import get_token_manager
    from .contenido import set_description
    from .prices import update_price
    cli = MeliClient(get_token_manager(), entry["meta"]["user_id"])
    for f in filas:
        try:
            if acc == "meli_descripcion":
                set_description(cli, f["id"], f["despues"] or "")
            elif acc == "meli_fotos":
                from .meli_fotos import poner_fotos
                poner_fotos(cli, f["id"], f["despues"])
            else:
                update_price(cli, f["id"], f["despues"], (entry.get("meta") or {}).get("variations", {}).get(f["id"]))
            f["ok"], f["error"] = True, ""
        except Exception as e:  # noqa: BLE001
            f["ok"], f["error"] = False, str(e)
    op = historial.registrar("MeLi", entry["tienda"], acc, desc, filas, entry.get("meta"), False, entry["id"])
    df = pd.DataFrame([{"producto": f.get("label") or f["id"], "resultado": "OK" if f["ok"] else "ERROR",
                        "error": f["error"]} for f in filas])
    df.attrs["op_id"] = op
    return df


def mostrar_resultado(df: pd.DataFrame) -> None:
    if df is None or df.empty:
        return
    ok = int((df["resultado"] == "OK").sum())
    err = len(df) - ok
    (st.success if not err else st.warning)(
        f"✅ {ok} OK" + (f" · ❌ {err} con error" if err else "")
        + (" · guardado en **Historial**" if df.attrs.get("op_id") else ""))
    if err:
        st.dataframe(df[df["resultado"] != "OK"], hide_index=True, width="stretch")
