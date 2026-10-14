"""Protección de marca: búsqueda de publicaciones de terceros, scoring de sospecha y registro de denuncias."""
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import pandas as pd

from .api import MeliClient, MeliError
from .token_store import GitHubTokenStore

KEYWORDS = [
    r"r[eé]plicas?", r"\baaa\b", r"triple\s*a", r"\b1\s*:\s*1\b", r"calidad\s+original", r"primera\s+calidad",
    r"s[ií]mil", r"inspirad[oa]s?", r"\bclon(es)?\b", r"\bg5\b", r"\bespejo\b", r"\balternativ[oa]s?\b",
    r"\bgen[eé]ric[oa]s?\b", r"\btipo\s+original\b", r"\bigual\s+al?\s+original\b", r"\bpremium\s+copy\b",
]
KW_RE = re.compile("|".join(KEYWORDS), re.I)
ITEM_RE = re.compile(r"\b(MLA)-?(\d{6,})", re.I)
PRODUCT_RE = re.compile(r"/p/(MLA\d{5,})", re.I)

ITEM_ATTRS = ("id,title,price,original_price,seller_id,official_store_id,permalink,condition,available_quantity,"
              "sold_quantity,attributes,seller_address,date_created,catalog_product_id,status,thumbnail")


# ---------------------------------------------------------------- persistencia (rama tokens del repo)
class ProteccionStore:
    def __init__(self):
        self.gh = GitHubTokenStore(path="proteccion.json")

    def load(self) -> dict:
        data, _ = self.gh.load()
        data.setdefault("autorizados", [])
        data.setdefault("denuncias", {})
        return data

    def set_autorizados(self, ids: list[str]) -> dict:
        def fn(d):
            d["autorizados"] = sorted(set(ids))
            d.setdefault("denuncias", {})
            return d
        return self.gh.update(fn, "autorizados")

    def add_denuncias(self, rows: list[dict]) -> dict:
        def fn(d):
            d.setdefault("autorizados", [])
            den = d.setdefault("denuncias", {})
            hoy = datetime.now().strftime("%Y-%m-%d")
            for r in rows:
                den[r["item_id"]] = {
                    "fecha": hoy, "titulo": r.get("titulo"), "precio": r.get("precio"),
                    "seller_id": str(r.get("seller_id")), "vendedor": r.get("vendedor"),
                    "link": r.get("link"), "busqueda": r.get("busqueda"), "estado_meli": r.get("estado"),
                }
            return d
        return self.gh.update(fn, f"denuncias +{len(rows)}")

    def update_estados(self, estados: dict) -> dict:
        def fn(d):
            for iid, est in estados.items():
                if iid in d.get("denuncias", {}):
                    d["denuncias"][iid]["estado_meli"] = est
                    d["denuncias"][iid]["verificado"] = datetime.now().strftime("%Y-%m-%d %H:%M")
            return d
        return self.gh.update(fn, "verificar denuncias")

    def remove_denuncias(self, ids: list[str]) -> dict:
        def fn(d):
            for i in ids:
                d.get("denuncias", {}).pop(i, None)
            return d
        return self.gh.update(fn, f"denuncias -{len(ids)}")


# ---------------------------------------------------------------- obtención de publicaciones
def parse_links(text: str) -> tuple[list[str], list[str]]:
    items, products = [], []
    for tok in re.split(r"[\s,;]+", text or ""):
        if not tok:
            continue
        p = PRODUCT_RE.search(tok)
        if p:
            products.append(p.group(1).upper())
            continue
        m = ITEM_RE.search(tok)
        if m:
            items.append(f"MLA{m.group(2)}")
    return list(dict.fromkeys(items)), list(dict.fromkeys(products))


def search_ids(client: MeliClient, q: str, max_results: int = 300) -> list[str]:
    ids, offset = [], 0
    while offset < max_results:
        r = client.get("/sites/MLA/search", params={"q": q, "offset": offset, "limit": 50})
        res = r.get("results", []) if isinstance(r, dict) else []
        ids.extend(x["id"] for x in res if x.get("id"))
        total = (r.get("paging") or {}).get("total", 0) if isinstance(r, dict) else 0
        offset += 50
        if not res or offset >= total or offset >= 1000:
            break
        time.sleep(0.2)
    return list(dict.fromkeys(ids))


def product_item_ids(client: MeliClient, product_id: str) -> list[str]:
    try:
        r = client.get(f"/products/{product_id}/items", params={"limit": 100})
    except MeliError:
        return []
    return [x.get("item_id") for x in r.get("results", []) if x.get("item_id")]


def fetch_items(client: MeliClient, ids: list[str]) -> list[dict]:
    chunks = [ids[i:i + 20] for i in range(0, len(ids), 20)]

    def get(chunk):
        try:
            res = client.get("/items", params={"ids": ",".join(chunk), "attributes": ITEM_ATTRS})
        except MeliError:
            return []
        return [x["body"] for x in res if isinstance(x, dict) and x.get("code") == 200]

    out = []
    with ThreadPoolExecutor(max_workers=6) as ex:
        for part in ex.map(get, chunks):
            out.extend(part)
    return out


def _attr(it, key):
    for a in it.get("attributes") or []:
        if a.get("id") == key:
            return a.get("value_name")
    return None


def item_row(it: dict, busqueda: str) -> dict:
    addr = it.get("seller_address") or {}
    return {
        "busqueda": busqueda,
        "item_id": it.get("id"),
        "titulo": it.get("title"),
        "precio": it.get("price"),
        "precio_original": it.get("original_price"),
        "seller_id": str(it.get("seller_id")),
        "tienda_oficial": it.get("official_store_id") is not None,
        "condicion": it.get("condition"),
        "stock": it.get("available_quantity"),
        "vendidos": it.get("sold_quantity"),
        "marca": _attr(it, "BRAND"),
        "modelo": _attr(it, "MODEL"),
        "ciudad": (addr.get("city") or {}).get("name"),
        "provincia": (addr.get("state") or {}).get("name"),
        "estado": it.get("status"),
        "creada": str(it.get("date_created") or "")[:10],
        "foto": it.get("thumbnail"),
        "link": it.get("permalink"),
    }


def sellers_info(client: MeliClient, seller_ids: list[str]) -> pd.DataFrame:
    def get(sid):
        try:
            u = client.get(f"/users/{sid}")
        except MeliError:
            return {"seller_id": sid}
        rep = u.get("seller_reputation") or {}
        addr = u.get("address") or {}
        return {
            "seller_id": sid,
            "vendedor": u.get("nickname"),
            "alta_cuenta": str(u.get("registration_date") or "")[:10],
            "reputacion": rep.get("level_id"),
            "mercadolider": rep.get("power_seller_status"),
            "ventas_totales": (rep.get("transactions") or {}).get("total"),
            "ciudad_vendedor": addr.get("city"),
            "provincia_vendedor": addr.get("state"),
            "perfil": u.get("permalink"),
        }

    with ThreadPoolExecutor(max_workers=6) as ex:
        return pd.DataFrame(list(ex.map(get, seller_ids)))


# ---------------------------------------------------------------- scoring
def reference_prices(df: pd.DataFrame, own_ids: set[str], manual: dict) -> dict:
    refs = {}
    for q, g in df.groupby("busqueda"):
        if manual.get(q):
            refs[q] = (float(manual[q]), "manual")
            continue
        own = g[g["seller_id"].isin(own_ids)]["precio"].dropna()
        if not own.empty:
            refs[q] = (float(own.median()), "tu tienda")
            continue
        off = g[g["tienda_oficial"]]["precio"].dropna()
        if not off.empty:
            refs[q] = (float(off.median()), "tiendas oficiales")
            continue
        refs[q] = (None, "sin referencia")
    return refs


def score(df: pd.DataFrame, refs: dict, thr: float, sellers: pd.DataFrame, denuncias: dict) -> pd.DataFrame:
    df = df.copy()
    if not sellers.empty:
        df = df.merge(sellers, on="seller_id", how="left")
    counts = df.groupby("seller_id")["item_id"].transform("nunique")
    hoy = pd.Timestamp.now()
    scores, flags_all, ratios, ref_col = [], [], [], []
    for (_, r), n in zip(df.iterrows(), counts):
        s, flags = 0, []
        ref, fuente = refs.get(r["busqueda"], (None, ""))
        ratio = r["precio"] / ref if ref and r["precio"] else None
        ratios.append(round(ratio * 100) if ratio else None)
        ref_col.append(ref)
        if ratio is not None and ratio < thr:
            s += 40
            flags.append(f"precio {round(ratio * 100)}% de ref ({fuente})")
            if ratio < thr - 0.2:
                s += 15
        kw = KW_RE.search(str(r["titulo"] or ""))
        if kw:
            s += 30
            flags.append(f"palabra «{kw.group(0)}»")
        if n >= 5:
            s += 10
            flags.append(f"{n} publicaciones del vendedor")
        alta = pd.to_datetime(r.get("alta_cuenta"), errors="coerce")
        if pd.notna(alta) and (hoy - alta).days < 365:
            s += 10
            flags.append("cuenta de menos de 1 año")
        rep = r.get("reputacion") if "reputacion" in df else "n/a"
        if rep is None or (isinstance(rep, float) and pd.isna(rep)) or str(rep).startswith(("1_", "2_")):
            s += 5
            flags.append("reputación baja o sin reputación")
        if r["item_id"] in denuncias:
            flags.append(f"ya denunciada {denuncias[r['item_id']].get('fecha')}")
        scores.append(min(s, 100))
        flags_all.append(" · ".join(flags))
    df["ref"] = ref_col
    df["precio_vs_ref_%"] = ratios
    df["score"] = scores
    df["señales"] = flags_all
    df["denunciada"] = df["item_id"].isin(denuncias.keys())
    return df.sort_values(["score", "precio_vs_ref_%"], ascending=[False, True])


def sellers_summary(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    g = df.groupby("seller_id")
    out = g.agg(
        vendedor=("vendedor", "first") if "vendedor" in df else ("seller_id", "first"),
        publicaciones=("item_id", "nunique"),
        score_max=("score", "max"),
        score_prom=("score", "mean"),
        precio_min=("precio", "min"),
        busquedas=("busqueda", lambda s: ", ".join(sorted(set(s)))[:120]),
        denunciadas=("denunciada", "sum"),
    ).reset_index()
    extra = [c for c in ["alta_cuenta", "reputacion", "mercadolider", "ventas_totales", "ciudad_vendedor",
                         "provincia_vendedor", "perfil"] if c in df]
    if extra:
        out = out.merge(df.drop_duplicates("seller_id")[["seller_id"] + extra], on="seller_id", how="left")
    out["score_prom"] = out["score_prom"].round(0)
    return out.sort_values(["score_max", "publicaciones"], ascending=False)
