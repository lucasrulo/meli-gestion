"""Conector Shopify Admin GraphQL multi-tienda.

Secrets (una tabla por tienda):

    [shopify.columbia]
    shop = "columbia-mhw.myshopify.com"
    token = "shpat_..."              # app personalizada (Admin API access token)
    # o, si la app es del Dev Dashboard:
    # client_id = "..."
    # client_secret = "..."
    vendor = ""                      # opcional: filtra una marca dentro de una tienda compartida (ej "MHW-ar")
    meli = "COLUMBIA"                # alias de la cuenta MeLi que corresponde (opcional)
    nombre = "Columbia"              # opcional, para mostrar
"""
import re
import threading
import time

import pandas as pd
import requests
import streamlit as st

from .config import secret

API_VERSION_DEFAULT = "2026-07"


class ShopifyError(Exception):
    pass


def stores() -> dict[str, dict]:
    raw = secret("shopify", {}) or {}
    out = {}
    for key, cfg in dict(raw).items():
        cfg = dict(cfg)
        if not cfg.get("shop"):
            continue
        cfg["shop"] = re.sub(r"^https?://", "", cfg["shop"]).strip("/")
        cfg.setdefault("nombre", key.capitalize())
        cfg["key"] = key
        out[key] = cfg
    return out


def stores_for_meli(alias: str | None) -> list[str]:
    """Tiendas vinculadas a una cuenta MeLi (por `meli = "ALIAS"`). Si ninguna lo declara, todas."""
    st_ = stores()
    a = (alias or "").strip().upper()
    linked = [k for k, c in st_.items() if str(c.get("meli", "")).strip().upper() == a and a]
    return linked or list(st_)


class ShopifyClient:
    _tokens: dict[str, tuple[str, float]] = {}
    _lock = threading.Lock()

    def __init__(self, key: str):
        cfg = stores().get(key)
        if not cfg:
            raise ShopifyError(f"Tienda Shopify «{key}» no configurada en secrets.")
        self.key, self.cfg = key, cfg
        self.shop = cfg["shop"]
        self.version = secret("SHOPIFY_API_VERSION", API_VERSION_DEFAULT)
        self.url = f"https://{self.shop}/admin/api/{self.version}/graphql.json"

    # ---------- auth: token fijo o client credentials ----------
    def _token(self, force: bool = False) -> str:
        if self.cfg.get("token"):
            return self.cfg["token"]
        with self._lock:
            tok, exp = self._tokens.get(self.key, ("", 0))
            if tok and not force and exp > time.time():
                return tok
            r = requests.post(f"https://{self.shop}/admin/oauth/access_token", timeout=30, data={
                "grant_type": "client_credentials",
                "client_id": self.cfg.get("client_id"), "client_secret": self.cfg.get("client_secret")})
            if r.status_code != 200:
                raise ShopifyError(f"{self.cfg['nombre']}: no pude obtener token ({r.status_code}) {r.text[:200]}")
            body = r.json()
            tok = body["access_token"]
            self._tokens[self.key] = (tok, time.time() + int(body.get("expires_in", 86000)) - 600)
            return tok

    def gql(self, query: str, variables: dict | None = None, retries: int = 6) -> dict:
        force = False
        for attempt in range(retries):
            try:
                r = requests.post(self.url, json={"query": query, "variables": variables or {}}, timeout=60,
                                  headers={"X-Shopify-Access-Token": self._token(force),
                                           "Content-Type": "application/json"})
            except requests.RequestException as e:
                if attempt == retries - 1:
                    raise ShopifyError(str(e))
                time.sleep(2 ** attempt)
                continue
            force = False
            if r.status_code == 401 and attempt < retries - 1 and not self.cfg.get("token"):
                force = True
                continue
            if r.status_code in (429, 502, 503, 504) and attempt < retries - 1:
                time.sleep(min(2 ** attempt, 20))
                continue
            if r.status_code != 200:
                raise ShopifyError(f"{self.cfg['nombre']} {r.status_code}: {r.text[:300]}")
            body = r.json()
            errs = body.get("errors") or []
            if errs:
                if any((e.get("extensions") or {}).get("code") == "THROTTLED" for e in errs) and attempt < retries - 1:
                    th = ((body.get("extensions") or {}).get("cost") or {}).get("throttleStatus") or {}
                    need = ((body.get("extensions") or {}).get("cost") or {}).get("requestedQueryCost", 500)
                    rate = th.get("restoreRate", 50) or 50
                    time.sleep(min(max(need - th.get("currentlyAvailable", 0), 50) / rate, 30))
                    continue
                raise ShopifyError(f"{self.cfg['nombre']}: " + "; ".join(e.get("message", str(e)) for e in errs)[:400])
            self._pace(body)
            return body.get("data") or {}
        raise ShopifyError(f"{self.cfg['nombre']}: sin respuesta tras reintentos")

    @staticmethod
    def _pace(body: dict) -> None:
        th = (((body.get("extensions") or {}).get("cost") or {}).get("throttleStatus")) or {}
        if th and th.get("currentlyAvailable", 1000) < 200:
            time.sleep(1.5)

    # ---------- lectura ----------
    VARIANTS_Q = """
    query($cursor: String) {
      productVariants(first: 250, after: $cursor) {
        pageInfo { hasNextPage endCursor }
        nodes {
          id sku price compareAtPrice inventoryQuantity title
          product { id title handle status vendor productType onlineStoreUrl }
        }
      }
    }"""

    def variants(self) -> pd.DataFrame:
        rows, cursor = [], None
        vendor = (self.cfg.get("vendor") or "").strip().lower()
        while True:
            d = self.gql(self.VARIANTS_Q, {"cursor": cursor})["productVariants"]
            for n in d["nodes"]:
                p = n.get("product") or {}
                if vendor and (p.get("vendor") or "").strip().lower() != vendor:
                    continue
                rows.append({
                    "tienda": self.key, "tienda_nombre": self.cfg["nombre"],
                    "variant_id": n["id"], "sku": (n.get("sku") or "").strip() or None,
                    "precio": float(n["price"]) if n.get("price") not in (None, "") else None,
                    "precio_tachado": float(n["compareAtPrice"]) if n.get("compareAtPrice") else None,
                    "stock": n.get("inventoryQuantity"), "variante": n.get("title"),
                    "product_id": p.get("id"), "producto": p.get("title"), "handle": p.get("handle"),
                    "estado": (p.get("status") or "").lower(), "vendor": p.get("vendor"),
                    "tipo": p.get("productType"), "url": p.get("onlineStoreUrl"),
                })
            if not d["pageInfo"]["hasNextPage"]:
                break
            cursor = d["pageInfo"]["endCursor"]
        return pd.DataFrame(rows, columns=VAR_COLS)

    PRODUCTS_Q = """
    query($ids: [ID!]!) {
      nodes(ids: $ids) {
        ... on Product { id title handle vendor productType tags descriptionHtml onlineStoreUrl
                         seo { title description } }
      }
    }"""

    def products(self, ids: list[str]) -> list[dict]:
        out = []
        for i in range(0, len(ids), 50):
            out += [n for n in self.gql(self.PRODUCTS_Q, {"ids": ids[i:i + 50]})["nodes"] if n]
        return out

    # ---------- escritura ----------
    def update_variant_prices(self, product_id: str, variants: list[dict]) -> None:
        """variants: [{"id": gid, "price": 123.0, "compareAtPrice": 150.0 | None}] (compareAtPrice opcional)"""
        q = """mutation($pid: ID!, $v: [ProductVariantsBulkInput!]!) {
                 productVariantsBulkUpdate(productId: $pid, variants: $v) { userErrors { field message } } }"""
        payload = []
        for v in variants:
            item = {"id": v["id"], "price": f"{float(v['price']):.2f}"}
            if "compareAtPrice" in v:
                item["compareAtPrice"] = None if v["compareAtPrice"] in (None, 0) else f"{float(v['compareAtPrice']):.2f}"
            payload.append(item)
        errs = self.gql(q, {"pid": product_id, "v": payload})["productVariantsBulkUpdate"]["userErrors"]
        if errs:
            raise ShopifyError("; ".join(f"{e.get('field')}: {e.get('message')}" for e in errs))

    def update_product_content(self, product_id: str, description_html: str | None = None,
                               seo_title: str | None = None, seo_description: str | None = None) -> None:
        q = """mutation($p: ProductUpdateInput!) {
                 productUpdate(product: $p) { product { id } userErrors { field message } } }"""
        p: dict = {"id": product_id}
        if description_html is not None:
            p["descriptionHtml"] = description_html
        seo = {k: v for k, v in (("title", seo_title), ("description", seo_description)) if v is not None}
        if seo:
            p["seo"] = seo
        errs = self.gql(q, {"p": p})["productUpdate"]["userErrors"]
        if errs:
            raise ShopifyError("; ".join(f"{e.get('field')}: {e.get('message')}" for e in errs))

    def shop_name(self) -> str:
        return self.gql("{ shop { name myshopifyDomain } }")["shop"]["name"]


# ---------------------------------------------------------------- caché
VAR_COLS = ["tienda", "tienda_nombre", "variant_id", "sku", "precio", "precio_tachado", "stock", "variante",
            "product_id", "producto", "handle", "estado", "vendor", "tipo", "url"]


@st.cache_data(ttl=3600, show_spinner=False)
def _cached_variants(key: str, nonce: int) -> pd.DataFrame:
    return ShopifyClient(key).variants()


def variants_for(keys: list[str], refresh: bool = False) -> pd.DataFrame:
    """Variantes de varias tiendas (caché 1 h). Las tiendas con error se informan y se saltean."""
    frames = []
    for k in keys:
        nk = f"shop_nonce_{k}"
        if refresh:
            st.session_state[nk] = int(time.time())
        try:
            frames.append(_cached_variants(k, st.session_state.get(nk, 0)))
        except ShopifyError as e:
            st.warning(f"Shopify {k}: {e}")
    if not frames:
        return pd.DataFrame(columns=VAR_COLS)
    return pd.concat(frames, ignore_index=True)


# ---------------------------------------------------------------- texto ↔ HTML
def text_to_html(txt: str) -> str:
    """Convierte la descripción en texto plano (estilo MeLi) a HTML semántico para Shopify."""
    out, lista = [], False
    for raw in (txt or "").splitlines():
        line = raw.strip()
        if not line:
            if lista:
                out.append("</ul>")
                lista = False
            continue
        esc = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        if re.match(r"^[-•*·]\s+", line):
            if not lista:
                out.append("<ul>")
                lista = True
            out.append(f"<li>{re.sub(r'^[-•*·]\s+', '', esc)}</li>")
            continue
        if lista:
            out.append("</ul>")
            lista = False
        if re.match(r"^P:\s*", line, re.I):
            out.append(f"<h3>{re.sub(r'^P:\s*', '', esc, flags=re.I)}</h3>")
        elif re.match(r"^R:\s*", line, re.I):
            out.append(f"<p>{re.sub(r'^R:\s*', '', esc, flags=re.I)}</p>")
        elif len(line) <= 60 and (line.isupper() or line.endswith(":")):
            out.append(f"<h2>{esc.rstrip(':').capitalize()}</h2>")
        else:
            out.append(f"<p>{esc}</p>")
    if lista:
        out.append("</ul>")
    return "\n".join(out)


def html_to_text(html: str) -> str:
    t = re.sub(r"<\s*(br|/p|/h\d|/li|/ul)\s*/?>", "\n", html or "", flags=re.I)
    t = re.sub(r"<li[^>]*>", "- ", t, flags=re.I)
    t = re.sub(r"<[^>]+>", "", t)
    t = t.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&nbsp;", " ")
    return re.sub(r"\n{3,}", "\n\n", t).strip()
