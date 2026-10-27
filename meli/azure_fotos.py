"""Fotos de catálogo en Azure Blob Storage (contenedor público) → Shopify, matcheando por código de artículo."""
import re
import xml.etree.ElementTree as ET
from urllib.parse import quote

import pandas as pd
import requests
import streamlit as st

from .catalog import norm
from .config import secret

DEFAULT_URL = "https://distriecomm.blob.core.windows.net/catalogo"
EXT = (".jpg", ".jpeg", ".png", ".webp")


def base_url() -> str:
    return str(secret("AZURE_CATALOGO_URL", DEFAULT_URL)).rstrip("/")


def _list(params: dict) -> ET.Element:
    r = requests.get(base_url(), params={"restype": "container", "comp": "list", **params}, timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f"Azure {r.status_code}: {r.text[:200]}")
    return ET.fromstring(r.content)


@st.cache_data(ttl=3600, show_spinner=False)
def carpetas() -> list[str]:
    root = _list({"delimiter": "/"})
    return sorted(p.findtext("Name").rstrip("/") for p in root.iter("BlobPrefix"))


def _parse(name: str) -> tuple[str, int]:
    base = name.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    m = re.match(r"^(.*?)[-_ ](\d{1,2})$", base)
    return (m.group(1), int(m.group(2))) if m else (base, 1)


@st.cache_data(ttl=3600, show_spinner=False)
def fotos(carpeta: str) -> pd.DataFrame:
    rows, marker = [], None
    while True:
        params = {"prefix": f"{carpeta}/", "maxresults": 5000}
        if marker:
            params["marker"] = marker
        root = _list(params)
        for b in root.iter("Blob"):
            name = b.findtext("Name")
            if not name or not name.lower().endswith(EXT):
                continue
            cod, n = _parse(name)
            mod = b.findtext("Properties/Last-Modified") or ""
            rows.append({"archivo": name, "codigo": cod, "n": n, "clave": norm(cod),
                         "url": f"{base_url()}/{quote(name)}", "modificado": pd.to_datetime(mod, utc=True, errors="coerce")})
        marker = root.findtext("NextMarker")
        if not marker:
            break
    return pd.DataFrame(rows, columns=["archivo", "codigo", "n", "clave", "url", "modificado"]).sort_values(["clave", "n"])


def matchear(P: pd.DataFrame, F: pd.DataFrame, M: pd.DataFrame | None = None) -> pd.DataFrame:
    """Por producto: fotos de Azure que le corresponden (por código de artículo/SKU, o handle)."""
    por_clave = {k: g for k, g in F.groupby("clave")} if not F.empty else {}
    shop_ult = {}
    if M is not None and not M.empty and "creado" in M:
        shop_ult = pd.to_datetime(M["creado"], utc=True, errors="coerce").groupby(M["product_id"]).max().to_dict()
    claves = list(por_clave)
    out = []
    for _, p in P.iterrows():
        cods = {norm(c) for c in p["codigos"] if c}
        hit = [c for c in cods if c in por_clave]
        if not hit:  # handle (algunos productos tienen SKUs vacíos) o prefijo de marca (ej MHW<sku>)
            h = norm(p["handle"])
            hit = [k for k in claves if len(k) >= 6 and (k in h or any(k.endswith(c) and len(c) >= 6 for c in cods))]
        fs = pd.concat([por_clave[c] for c in hit]).drop_duplicates("archivo").sort_values("n") if hit else F.iloc[0:0]
        az_mod = fs["modificado"].max() if len(fs) and "modificado" in fs else pd.NaT
        sh = shop_ult.get(p["product_id"], pd.NaT)
        out.append({"product_id": p["product_id"], "titulo": p["titulo"], "foto": p["foto"], "estado": p["estado"],
                    "n_shopify": int(p["n_fotos"]), "n_azure": len(fs), "codigo_azure": ", ".join(sorted(set(fs["codigo"])))[:80],
                    "urls": fs["url"].tolist(), "skus": p["skus"], "codigos": ", ".join(p["codigos"][:4]),
                    "azure_mod": az_mod, "shopify_carga": sh,
                    "cambio_azure": bool(pd.notna(az_mod) and pd.notna(sh) and az_mod > sh)})
    return pd.DataFrame(out)
