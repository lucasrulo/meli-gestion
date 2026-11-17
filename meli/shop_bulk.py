"""Operaciones masivas de Shopify.

- catalogo(): lee TODO el catálogo de una tienda con una Bulk Operation (productos + variantes + fotos + metacampos)
  en un par de minutos, sin paginar producto por producto.
- ejecutar(): corre una mutación para muchas filas. Pocas filas → llamadas normales en paralelo;
  muchas filas → Bulk Mutation (archivo JSONL + bulkOperationRunMutation), que no consume límite de API.
"""
import io
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import requests
import streamlit as st

from .shopify import ShopifyClient, ShopifyError, stores

BULK_MIN = 60          # desde cuántas filas conviene una Bulk Mutation
POLL_MAX_S = 20 * 60   # espera máxima

CATALOGO_Q = """
{
  products {
    edges { node {
      id title handle status vendor productType tags descriptionHtml onlineStoreUrl totalInventory updatedAt createdAt
      seo { title description }
      options { id name optionValues { id name } }
      variants { edges { node {
        id sku barcode price compareAtPrice inventoryQuantity title
        inventoryItem { measurement { weight { value unit } } }
      } } }
      media { edges { node { ... on MediaImage { id alt mediaContentType createdAt image { url } } } } }
      metafields { edges { node { id namespace key type value } } }
    } }
  }
}"""

PROD_COLS = ["tienda", "product_id", "titulo", "handle", "estado", "vendor", "tipo", "tags", "descripcion_html",
             "seo_title", "seo_description", "url", "stock", "actualizado", "creado", "n_variantes", "n_fotos", "foto",
             "skus", "codigos", "opciones"]

COLOR_OPC = ("color", "colour", "colores", "color principal")


# ---------------------------------------------------------------- bulk query
def _poll(cli: ShopifyClient, op_id: str, progress=None, label: str = "") -> dict:
    q = "query($id: ID!) { bulkOperation(id: $id) { id status errorCode objectCount url partialDataUrl } }"
    t0, espera = time.time(), 1.5
    while True:
        op = cli.gql(q, {"id": op_id})["bulkOperation"]
        if progress:
            progress(op)
        if op["status"] in ("COMPLETED", "FAILED", "CANCELED", "EXPIRED"):
            return op
        if time.time() - t0 > POLL_MAX_S:
            raise ShopifyError(f"La operación masiva {label} sigue corriendo después de 20 min (id {op_id}).")
        time.sleep(espera)
        espera = min(espera * 1.4, 8)


def _jsonl(url: str | None) -> list[dict]:
    if not url:
        return []
    r = requests.get(url, timeout=300)
    r.raise_for_status()
    return [json.loads(x) for x in r.text.splitlines() if x.strip()]


def bulk_query(cli: ShopifyClient, query: str, progress=None) -> list[dict]:
    m = """mutation($q: String!) { bulkOperationRunQuery(query: $q) {
             bulkOperation { id status } userErrors { field message } } }"""
    res = cli.gql(m, {"q": query})["bulkOperationRunQuery"]
    if res["userErrors"]:
        raise ShopifyError("; ".join(e["message"] for e in res["userErrors"]))
    op = _poll(cli, res["bulkOperation"]["id"], progress, "de lectura")
    if op["status"] != "COMPLETED":
        raise ShopifyError(f"Lectura masiva {op['status']}: {op.get('errorCode')}")
    return _jsonl(op.get("url"))


def _codigos(skus: list[str], handle: str) -> list[str]:
    from .inconsistencias import strip_size
    out = {strip_size(s) for s in skus if s}
    out |= {s.upper() for s in skus if s}
    return sorted(x for x in out if x)


def parse_catalogo(lines: list[dict], key: str, vendor: str = "") -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame,
                                                                             pd.DataFrame]:
    prods, vars_, media, metas = {}, [], [], []
    for x in lines:
        gid = str(x.get("id") or "")
        par = x.get("__parentId")
        if not par and "/Product/" in gid:
            prods[gid] = x
        elif "/ProductVariant/" in gid:
            w = ((((x.get("inventoryItem") or {}).get("measurement") or {}).get("weight")) or {})
            vars_.append({"product_id": par, "variant_id": gid, "sku": x.get("sku") or "", "barcode": x.get("barcode") or "",
                          "precio": float(x["price"]) if x.get("price") else None,
                          "precio_tachado": float(x["compareAtPrice"]) if x.get("compareAtPrice") else None,
                          "stock": x.get("inventoryQuantity"), "variante": x.get("title"),
                          "peso": w.get("value"), "peso_unidad": w.get("unit")})
        elif "/MediaImage/" in gid:
            media.append({"product_id": par, "media_id": gid, "alt": x.get("alt") or "",
                          "url": (x.get("image") or {}).get("url"), "creado": x.get("createdAt") or ""})
        elif "/Metafield/" in gid:
            metas.append({"product_id": par, "metafield_id": gid, "namespace": x.get("namespace"), "key": x.get("key"),
                          "type": x.get("type"), "value": x.get("value")})
    V = pd.DataFrame(vars_, columns=["product_id", "variant_id", "sku", "barcode", "precio", "precio_tachado", "stock",
                                     "variante", "peso", "peso_unidad"])
    M = pd.DataFrame(media, columns=["product_id", "media_id", "alt", "url", "creado"])
    MF = pd.DataFrame(metas, columns=["product_id", "metafield_id", "namespace", "key", "type", "value"])
    vg = V.groupby("product_id")
    skus = vg["sku"].apply(list).to_dict() if not V.empty else {}
    nfot = M.groupby("product_id").size().to_dict() if not M.empty else {}
    foto1 = M.drop_duplicates("product_id").set_index("product_id")["url"].to_dict() if not M.empty else {}
    rows = []
    for pid, p in prods.items():
        if vendor and str(p.get("vendor", "")).strip().lower() != vendor.strip().lower():
            continue
        sk = skus.get(pid, [])
        rows.append({
            "tienda": key, "product_id": pid, "titulo": p.get("title"), "handle": p.get("handle"),
            "estado": p.get("status"), "vendor": p.get("vendor"), "tipo": p.get("productType") or "",
            "tags": list(p.get("tags") or []), "descripcion_html": p.get("descriptionHtml") or "",
            "seo_title": (p.get("seo") or {}).get("title") or "", "seo_description": (p.get("seo") or {}).get("description") or "",
            "url": p.get("onlineStoreUrl"), "stock": p.get("totalInventory"), "actualizado": p.get("updatedAt"),
            "creado": (p.get("createdAt") or "")[:10],
            "n_variantes": len(sk), "n_fotos": nfot.get(pid, 0), "foto": foto1.get(pid) or "",
            "skus": ", ".join(s for s in sk if s)[:200], "codigos": _codigos(sk, p.get("handle") or ""),
            "opciones": [{"id": o.get("id"), "name": o.get("name"),
                          "values": [{"id": v.get("id"), "name": v.get("name")} for v in (o.get("optionValues") or [])]}
                         for o in (p.get("options") or [])],
        })
    P = pd.DataFrame(rows, columns=PROD_COLS)
    ids = set(P["product_id"])
    return P, V[V["product_id"].isin(ids)], M[M["product_id"].isin(ids)], MF[MF["product_id"].isin(ids)]


# ---------------------------------------------------------------- color del producto
def _txt_meta(tipo: str, valor) -> str | None:
    """Valor de un metacampo de texto legible (None si es una referencia, ej. metaobjeto)."""
    tipo = str(tipo or "")
    if "reference" in tipo:
        return None
    if tipo.startswith("list."):
        try:
            return " / ".join(str(x) for x in json.loads(valor or "[]"))
        except (ValueError, TypeError):
            return str(valor or "")
    return str(valor or "")


def fuentes_color(P: pd.DataFrame, MF: pd.DataFrame) -> dict[str, int]:
    """Dónde está cargado el color en esta tienda → cuántos productos lo tienen. Claves: 'opcion' o 'meta:ns.key'."""
    out: dict[str, int] = {}
    n_opt = sum(1 for ops in P.get("opciones", []) if any(str(o.get("name", "")).strip().lower() in COLOR_OPC
                                                           for o in (ops or [])))
    if n_opt:
        out["opcion"] = n_opt
    if not MF.empty:
        m = MF[MF["key"].str.lower().str.contains("color", na=False) & ~MF["type"].str.contains("reference", na=False)]
        for (ns, k), g in m.groupby(["namespace", "key"]):
            out[f"meta:{ns}.{k}"] = int(g["product_id"].nunique())
    return dict(sorted(out.items(), key=lambda x: -x[1]))


def color_por_producto(P: pd.DataFrame, MF: pd.DataFrame, fuente: str | None = None) -> pd.DataFrame:
    """product_id → color (+ datos para modificarlo). Si no se indica fuente, usa la que más productos cubre."""
    fs = fuentes_color(P, MF)
    fuente = fuente or (next(iter(fs)) if fs else None)
    cols = ["product_id", "color", "fuente", "option_id", "value_id", "n_valores", "mf_type", "mf_raw"]
    if not fuente:
        return pd.DataFrame(columns=cols)
    rows = []
    if fuente == "opcion":
        for _, r in P.iterrows():
            o = next((o for o in (r["opciones"] or []) if str(o.get("name", "")).strip().lower() in COLOR_OPC), None)
            if o:
                vals = o.get("values") or []
                rows.append({"product_id": r["product_id"], "color": " / ".join(v["name"] for v in vals),
                             "fuente": f"Opción «{o['name']}»", "option_id": o["id"],
                             "value_id": vals[0]["id"] if len(vals) == 1 else None, "n_valores": len(vals), "mf_type": None,
                             "mf_raw": None})
    else:
        ns, k = fuente[5:].split(".", 1)
        m = MF[(MF["namespace"] == ns) & (MF["key"] == k)].drop_duplicates("product_id")
        for _, r in m.iterrows():
            rows.append({"product_id": r["product_id"], "color": _txt_meta(r["type"], r["value"]) or "",
                         "fuente": f"Metacampo {ns}.{k}", "option_id": None, "value_id": None, "n_valores": 1,
                         "mf_type": r["type"], "mf_raw": r["value"]})
    return pd.DataFrame(rows, columns=cols)


@st.cache_data(ttl=3600, show_spinner=False)
def _catalogo_cached(key: str, nonce: float):
    cli = ShopifyClient(key)
    lines = bulk_query(cli, CATALOGO_Q)
    return parse_catalogo(lines, key, cli.cfg.get("vendor") or "")


def catalogo(key: str, refresh: bool = False):
    """(productos, variantes, fotos, metacampos) de una tienda. Caché 1 h; refresh=True relee."""
    nk = f"cat_nonce_{key}"
    if refresh or nk not in st.session_state:
        st.session_state[nk] = time.time()
    return _catalogo_cached(key, st.session_state[nk])


def invalidar(key: str) -> None:
    st.session_state[f"cat_nonce_{key}"] = time.time()


# ---------------------------------------------------------------- mutaciones masivas
def _errores(data: dict) -> str:
    """Busca userErrors en la respuesta de una mutación."""
    msgs = []
    for v in (data or {}).values():
        if isinstance(v, dict):
            for e in v.get("userErrors") or []:
                msgs.append(f"{e.get('field') or ''} {e.get('message')}".strip())
    return "; ".join(msgs)


def _staged_upload(cli: ShopifyClient, contenido: bytes) -> str:
    m = """mutation { stagedUploadsCreate(input: [{ resource: BULK_MUTATION_VARIABLES, filename: "vars.jsonl",
             mimeType: "text/jsonl", httpMethod: POST }]) {
             userErrors { field message } stagedTargets { url resourceUrl parameters { name value } } } }"""
    res = cli.gql(m)["stagedUploadsCreate"]
    if res["userErrors"]:
        raise ShopifyError("; ".join(e["message"] for e in res["userErrors"]))
    t = res["stagedTargets"][0]
    params = [(p["name"], (None, p["value"])) for p in t["parameters"]]
    files = params + [("file", ("vars.jsonl", io.BytesIO(contenido), "text/jsonl"))]  # file va último
    r = requests.post(t["url"], files=files, timeout=300)
    if r.status_code not in (200, 201, 204):
        raise ShopifyError(f"No pude subir el archivo de la operación masiva ({r.status_code}): {r.text[:200]}")
    return next(p["value"] for p in t["parameters"] if p["name"] == "key")


def ejecutar(key: str, mutation: str, variables: list[dict], progress=None, bulk_min: int | None = None,
             version: str | None = None) -> list[dict]:
    """Corre `mutation` una vez por cada dict de `variables`.
    Devuelve [{ok: bool, error: str, data: dict}] en el mismo orden."""
    cli = ShopifyClient(key)
    n = len(variables)
    bulk_min = BULK_MIN if bulk_min is None else bulk_min
    if not n:
        return []
    if n < bulk_min or version:
        out: list[dict | None] = [None] * n

        def one(i):
            try:
                data = cli.gql(mutation, variables[i], version=version)
                err = _errores(data)
                return i, {"ok": not err, "error": err, "data": data}
            except Exception as e:  # noqa: BLE001
                return i, {"ok": False, "error": str(e), "data": {}}

        with ThreadPoolExecutor(max_workers=4) as ex:   # el progreso se actualiza en el hilo principal
            for k, fut in enumerate(as_completed([ex.submit(one, i) for i in range(n)]), 1):
                i, r = fut.result()
                out[i] = r
                if progress:
                    progress(k / n)
        return out  # type: ignore[return-value]

    # ---- Bulk Mutation
    contenido = "\n".join(json.dumps(v, ensure_ascii=False) for v in variables).encode()
    path = _staged_upload(cli, contenido)
    m = """mutation($m: String!, $p: String!) { bulkOperationRunMutation(mutation: $m, stagedUploadPath: $p) {
             bulkOperation { id status } userErrors { field message } } }"""
    res = cli.gql(m, {"m": mutation, "p": path})["bulkOperationRunMutation"]
    if res["userErrors"]:
        raise ShopifyError("; ".join(e["message"] for e in res["userErrors"]))
    op = _poll(cli, res["bulkOperation"]["id"],
               (lambda o: progress(min(int(o.get("objectCount") or 0) / n, 0.99))) if progress else None, "de escritura")
    lines = _jsonl(op.get("url") or op.get("partialDataUrl"))
    out = [{"ok": False, "error": f"Sin resultado (operación {op['status']})", "data": {}} for _ in range(n)]
    for ln in lines:
        i = ln.get("__lineNumber")
        if i is None or i >= n:
            continue
        data = ln.get("data") or {}
        err = _errores(data) or "; ".join(e.get("message", "") for e in ln.get("errors") or [])
        out[i] = {"ok": not err, "error": err, "data": data}
    if progress:
        progress(1.0)
    return out


def tiendas() -> dict[str, dict]:
    return stores()
