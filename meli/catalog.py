"""Índice SKU → publicación para una cuenta de MeLi.

Escanea todas las publicaciones (activas y pausadas), trae el detalle en
multiget de a 20 y arma una tabla con una fila por SKU (item o variación).
Toma el SKU de SELLER_SKU (atributo) y de seller_custom_field.
"""
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from .api import MeliClient


def scan_item_ids(client: MeliClient, status: str | None = None) -> list[str]:
    params = {"search_type": "scan", "limit": 100}
    if status:
        params["status"] = status
    r = client.get(f"/users/{client.user_id}/items/search", params=params)
    ids = list(r.get("results", []))
    scroll = r.get("scroll_id")
    while scroll:
        r = client.get(
            f"/users/{client.user_id}/items/search",
            params={"search_type": "scan", "scroll_id": scroll, "limit": 100},
        )
        batch = r.get("results", [])
        if not batch:
            break
        ids.extend(batch)
        scroll = r.get("scroll_id") or scroll
    return list(dict.fromkeys(ids))


def multiget(client: MeliClient, ids: list[str], workers: int = 6) -> list[dict]:
    chunks = [ids[i:i + 20] for i in range(0, len(ids), 20)]

    def fetch(chunk):
        res = client.get("/items", params={"ids": ",".join(chunk), "include_attributes": "all"})
        return [x["body"] for x in res if isinstance(x, dict) and x.get("code") == 200]

    out: list[dict] = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for part in ex.map(fetch, chunks):
            out.extend(part)
    return out


def _skus(obj: dict) -> set[str]:
    found = set()
    scf = obj.get("seller_custom_field")
    if scf:
        found.add(str(scf).strip())
    for a in obj.get("attributes") or []:
        if a.get("id") == "SELLER_SKU" and a.get("value_name"):
            found.add(str(a["value_name"]).strip())
    return {s for s in found if s}


def build_index(items: list[dict]) -> pd.DataFrame:
    rows = []
    for it in items:
        variations = it.get("variations") or []
        base = {
            "item_id": it["id"],
            "titulo": it.get("title"),
            "estado": it.get("status"),
            "precio_actual": it.get("price"),
            "precio_original": it.get("original_price"),
            "stock": it.get("available_quantity"),
            "catalogo": bool(it.get("catalog_listing")),
            "user_product_id": it.get("user_product_id"),
            "variaciones": len(variations),
            "variation_ids": ",".join(str(v["id"]) for v in variations),
            "permalink": it.get("permalink"),
        }
        item_skus = _skus(it)
        for s in item_skus:
            rows.append({**base, "sku": s, "variation_id": None})
        for v in variations:
            for s in _skus(v) - item_skus:
                rows.append({**base, "sku": s, "variation_id": v.get("id")})
        if not item_skus and not any(_skus(v) for v in variations):
            rows.append({**base, "sku": None, "variation_id": None})
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=["item_id", "sku", "sku_norm"])
    df["sku_norm"] = df["sku"].fillna("").astype(str).str.strip().str.upper()
    return df


def load_index(client: MeliClient, statuses=("active", "paused")) -> pd.DataFrame:
    ids: list[str] = []
    for st_ in statuses:
        ids.extend(scan_item_ids(client, st_))
    ids = list(dict.fromkeys(ids))
    return build_index(multiget(client, ids))


def match(index: pd.DataFrame, keys: pd.Series, prefix: bool = False) -> pd.DataFrame:
    """Devuelve una fila por (clave_input, item_id). Acepta SKU o item_id (MLA...)."""
    out = []
    by_item = index.drop_duplicates("item_id").set_index("item_id")
    for raw in keys.dropna().astype(str):
        k = raw.strip().upper()
        if not k:
            continue
        if k.startswith("MLA") and k[3:].isdigit():
            if k in by_item.index:
                r = by_item.loc[k].to_dict()
                r["item_id"] = k
                out.append({"clave": raw, **r})
            else:
                out.append({"clave": raw, "item_id": None})
            continue
        hits = index[index["sku_norm"].str.startswith(k)] if prefix else index[index["sku_norm"] == k]
        if hits.empty:
            out.append({"clave": raw, "item_id": None})
        else:
            for _, r in hits.drop_duplicates("item_id").iterrows():
                out.append({"clave": raw, **r.to_dict()})
    df = pd.DataFrame(out)
    return df.drop(columns=["sku_norm"], errors="ignore")
