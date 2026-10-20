"""Cruce MeLi ↔ Shopify por SKU / modelo-color, reglas de precio y aplicación en ambos canales."""
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import pandas as pd
import streamlit as st

from .api import MeliClient
from .carga import redondear
from .catalog import match, norm
from .excel import to_number
from .inconsistencias import strip_size
from .prices import update_price
from .shopify import ShopifyClient


def _moda(s: pd.Series):
    s = pd.to_numeric(s, errors="coerce").dropna()
    if s.empty:
        return None
    vc = s.value_counts()
    return float(vc[vc == vc.max()].index.max())


def _fmt(x):
    return "" if x is None or pd.isna(x) else f"${x:,.0f}".replace(",", ".")


# ---------------------------------------------------------------- matching
def shop_match(variants: pd.DataFrame, claves, mode: str) -> pd.DataFrame:
    m, _, _ = str(mode).partition("|")
    v = variants[variants["sku"].notna()].copy()
    v["_n"] = v["sku"].map(norm)
    out = []
    for raw in pd.Series(list(claves)).dropna().astype(str):
        k, kn = raw.strip(), norm(raw)
        if not kn:
            continue
        if m == "modelo":
            hits = v[v["sku"].map(strip_size) == k.upper()]
        elif m == "exacto":
            hits = v[v["_n"] == kn]
        elif m == "contiene":
            hits = v[v["_n"].str.contains(kn, regex=False)]
        else:
            hits = v[v["_n"].str.startswith(kn)]
        for r in hits.to_dict("records"):
            out.append({"clave": k, **r})
    df = pd.DataFrame(out)
    return df.drop(columns=["_n"], errors="ignore") if not df.empty else pd.DataFrame(columns=["clave", "variant_id"])


def meli_match(index: pd.DataFrame, claves, mode: str) -> pd.DataFrame:
    if str(mode).startswith("modelo"):  # igualdad exacta de modelo-color (SKU sin talle)
        ix = index[index["sku"].notna()].copy()
        ix["_mc"] = ix["sku"].map(strip_size)
        parts = [ix[ix["_mc"] == str(c).strip().upper()].assign(clave=c) for c in claves]
        det = pd.concat(parts, ignore_index=True).drop(columns=["_mc"]) if parts else pd.DataFrame()
        if det.empty:
            return pd.DataFrame(columns=["clave", "item_id", "precio_lista", "precio_original"])
    else:
        det = match(index, claves, mode=mode)
    det = det[det["item_id"].notna()].copy()
    if det.empty:
        return pd.DataFrame(columns=["clave", "item_id", "precio_lista"])
    det["precio_lista"] = det.apply(
        lambda r: to_number(r.get("precio_original")) or to_number(r.get("precio_actual")), axis=1)
    return det


def lookup(index: pd.DataFrame, variants: pd.DataFrame, claves, mode: str) -> pd.DataFrame:
    md, sd = meli_match(index, claves, mode), shop_match(variants, claves, mode)
    rows = []
    for c in claves:
        m = md[md["clave"] == c].drop_duplicates("item_id")
        s = sd[sd["clave"] == c] if not sd.empty else sd
        mp, sp = _moda(m["precio_lista"]), _moda(s["precio"]) if not s.empty else None
        notas = []
        if m.empty:
            notas.append("no está en MeLi")
        elif m["precio_lista"].nunique() > 1:
            notas.append(f"MeLi con precios distintos {_fmt(m['precio_lista'].min())}–{_fmt(m['precio_lista'].max())}")
        if s.empty:
            notas.append("no está en Shopify")
        elif s["precio"].nunique() > 1:
            notas.append(f"Shopify con precios distintos {_fmt(s['precio'].min())}–{_fmt(s['precio'].max())}")
        if not m.empty and m["precio_original"].notna().any():
            notas.append("MeLi en promo")
        if not s.empty and s["precio_tachado"].notna().any():
            notas.append("Shopify con tachado")
        rows.append({
            "clave": c,
            "meli_actual": mp, "shop_actual": sp,
            "dif_%": round((mp / sp - 1) * 100, 1) if mp and sp else None,
            "meli_publ": int(m["item_id"].nunique()), "shop_var": int(len(s)),
            "estado": "✅" if not notas else "⚠️ " + " · ".join(notas),
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- análisis de catálogo completo
def analisis(meli_index: pd.DataFrame, variants: pd.DataFrame, nivel: str = "modelo") -> pd.DataFrame:
    keyf = strip_size if nivel == "modelo" else (lambda x: None if x is None or pd.isna(x) else str(x).strip().upper())
    m = meli_index[meli_index["sku"].notna()].copy()
    m["clave"] = m["sku"].map(keyf)
    m["precio_lista"] = m.apply(lambda r: to_number(r.get("precio_original")) or to_number(r.get("precio_actual")),
                                axis=1)
    mi = m.drop_duplicates(["clave", "item_id"])
    gm = mi.groupby("clave").agg(
        titulo=("titulo", "first"), meli_publ=("item_id", "nunique"), meli_precio=("precio_lista", _moda),
        meli_min=("precio_lista", "min"), meli_max=("precio_lista", "max"),
        meli_stock=("stock", "sum"), meli_promo=("precio_original", lambda s: bool(s.notna().any())),
        meli_link=("permalink", "first"),
        **({"cuenta": ("cuenta", "first")} if "cuenta" in mi else {}),
    )
    s = variants[variants["sku"].notna()].copy()
    s["clave"] = s["sku"].map(keyf)
    gs = s.groupby("clave").agg(
        producto=("producto", "first"), tienda=("tienda_nombre", "first"), shop_var=("variant_id", "nunique"),
        shop_precio=("precio", _moda), shop_min=("precio", "min"), shop_max=("precio", "max"),
        shop_tachado=("precio_tachado", "max"), shop_stock=("stock", "sum"), shop_estado=("estado", "first"),
        shop_link=("url", "first"),
    )
    df = gm.join(gs, how="outer").reset_index()
    df["nombre"] = df["titulo"].fillna(df["producto"])
    df["dif_%"] = ((df["meli_precio"] / df["shop_precio"] - 1) * 100).round(1)

    def cat(r):
        if pd.isna(r["meli_precio"]):
            return "Solo Shopify"
        if pd.isna(r["shop_precio"]):
            return "Solo MeLi"
        if abs(r["dif_%"]) < 0.5:
            return "Igual"
        return "MeLi más caro" if r["dif_%"] > 0 else "MeLi más barato"

    df["situacion"] = df.apply(cat, axis=1)
    return df


# ---------------------------------------------------------------- planes de cambio
def plan_meli(index: pd.DataFrame, claves_precio: dict[str, float], mode: str) -> pd.DataFrame:
    md = meli_match(index, list(claves_precio), mode).drop_duplicates("item_id")
    if md.empty:
        return md
    md["precio_nuevo"] = md["clave"].map(claves_precio)
    md = md[md["precio_nuevo"].notna() & (md["precio_nuevo"] > 0)]
    return md[md["precio_nuevo"].round(2) != md["precio_lista"].round(2)]


def plan_shop(variants: pd.DataFrame, claves_precio: dict[str, float], mode: str, tachado: str) -> pd.DataFrame:
    sd = shop_match(variants, list(claves_precio), mode).drop_duplicates("variant_id")
    if sd.empty:
        return sd
    sd["precio_nuevo"] = sd["clave"].map(claves_precio)
    sd = sd[sd["precio_nuevo"].notna() & (sd["precio_nuevo"] > 0)]
    sd = sd[sd["precio_nuevo"].round(2) != sd["precio"].round(2)].copy()
    if tachado == "quitar":
        sd["tachado_nuevo"] = None
    elif tachado == "anterior":
        sd["tachado_nuevo"] = sd.apply(lambda r: r["precio"] if r["precio_nuevo"] < r["precio"] else None, axis=1)
    else:
        sd["tachado_nuevo"] = sd["precio_tachado"]
    return sd


TACHADO = {
    "mantener": "No tocar el precio tachado",
    "anterior": "Si baja, mostrar el precio anterior tachado",
    "quitar": "Quitar el precio tachado",
}


# ---------------------------------------------------------------- aplicar
def aplicar(meli_rows: pd.DataFrame, shop_rows: pd.DataFrame, meli_clients: dict[str, MeliClient],
            default_uid: str, tachado: str) -> pd.DataFrame:
    """Ejecuta los cambios en ambos canales con barra de progreso. Devuelve un resultado unificado."""
    tareas = []
    for r in (meli_rows.to_dict("records") if meli_rows is not None and not meli_rows.empty else []):
        tareas.append(("MeLi", r))
    por_prod = defaultdict(list)
    for r in (shop_rows.to_dict("records") if shop_rows is not None and not shop_rows.empty else []):
        por_prod[(r["tienda"], r["product_id"])].append(r)
    for (tienda, pid), vs in por_prod.items():
        tareas.append(("Shopify", {"tienda": tienda, "product_id": pid, "variantes": vs}))
    if not tareas:
        return pd.DataFrame()

    shop_clients: dict[str, ShopifyClient] = {}

    def run(t):
        canal, r = t
        if canal == "MeLi":
            cli = meli_clients.get(str(r.get("uid") or default_uid)) or meli_clients[default_uid]
            update_price(cli, r["item_id"], r["precio_nuevo"], r.get("variation_ids"))
            return [{"canal": "MeLi", "clave": r["clave"], "id": r["item_id"], "titulo": r.get("titulo"),
                     "antes": r["precio_lista"], "despues": r["precio_nuevo"]}]
        cli = shop_clients.setdefault(r["tienda"], ShopifyClient(r["tienda"]))
        payload = []
        for v in r["variantes"]:
            item = {"id": v["variant_id"], "price": v["precio_nuevo"]}
            if tachado != "mantener":
                item["compareAtPrice"] = v.get("tachado_nuevo")
            payload.append(item)
        cli.update_variant_prices(r["product_id"], payload)
        return [{"canal": "Shopify", "clave": v["clave"], "id": v.get("sku"), "titulo": v.get("producto"),
                 "antes": v["precio"], "despues": v["precio_nuevo"]} for v in r["variantes"]]

    bar = st.progress(0.0, text=f"Aplicando… 0/{len(tareas)}")
    out = []
    with ThreadPoolExecutor(max_workers=4) as ex:
        futs = {ex.submit(run, t): t for t in tareas}
        for i, f in enumerate(as_completed(futs), 1):
            canal, r = futs[f]
            try:
                for row in f.result():
                    out.append({**row, "resultado": "OK", "error": ""})
            except Exception as e:  # noqa: BLE001
                if canal == "MeLi":
                    out.append({"canal": "MeLi", "clave": r.get("clave"), "id": r.get("item_id"),
                                "titulo": r.get("titulo"), "antes": r.get("precio_lista"),
                                "despues": r.get("precio_nuevo"), "resultado": "ERROR", "error": str(e)[:400]})
                else:
                    for v in r["variantes"]:
                        out.append({"canal": "Shopify", "clave": v.get("clave"), "id": v.get("sku"),
                                    "titulo": v.get("producto"), "antes": v.get("precio"),
                                    "despues": v.get("precio_nuevo"), "resultado": "ERROR", "error": str(e)[:400]})
            bar.progress(i / len(tareas), text=f"Aplicando… {i}/{len(tareas)}")
    bar.empty()
    res = pd.DataFrame(out)
    res["procesado"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return res


def regla_precio(base, factor: float, how: str):
    if base is None or pd.isna(base):
        return None
    return redondear(base * factor, how)
