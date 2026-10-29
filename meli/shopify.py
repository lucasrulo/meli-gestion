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


# Tiendas de Distrinando (mismo formato que dashboard-distrinando / reposicion-distrinando: secrets TOKEN_<MARCA>)
DEFAULT_STORES = {
    "reebok": {"shop": "reebok-ar.myshopify.com", "secret": "TOKEN_REEBOK", "nombre": "Reebok", "meli": "REEBOK"},
    "columbia": {"shop": "columbia-ar.myshopify.com", "secret": "TOKEN_COLUMBIA", "nombre": "Columbia", "meli": "COLUMBIA"},
    "crocs": {"shop": "crocs-ar.myshopify.com", "secret": "TOKEN_CROCS", "nombre": "Crocs", "meli": "CROCS"},
    "kappa": {"shop": "kappa-ar.myshopify.com", "secret": "TOKEN_KAPPA", "nombre": "Kappa", "meli": "KAPPA"},
    "piccadilly": {"shop": "piccadilly-ar.myshopify.com", "secret": "TOKEN_PICCADILLY", "nombre": "Piccadilly",
                   "meli": "PICCADILLY"},
}
# Marcas que viven dentro de otra tienda y se separan por vendor (mismo token que la tienda que las contiene).
# Se pueden ajustar con secrets: SHOP_MHW / TOKEN_MHW / VENDOR_MHW (idem SOREL).
VENDOR_STORES = {
    "mhw": {"shop": "columbia-mhw.myshopify.com", "nombre": "Mountain Hardwear", "vendor": "MHW-ar", "meli": ""},
    "sorel": {"shop": "columbia-sorel.myshopify.com", "nombre": "Sorel", "vendor": "Sorel-ar", "meli": ""},
}
_SHOP_KEYS = ("shop", "store", "domain", "url", "shop_url", "myshopify")
_TOKEN_KEYS = ("token", "access_token", "admin_token", "api_token", "shpat")


def _norm_shop(v: str) -> str:
    v = re.sub(r"^https?://", "", str(v or "")).strip().strip("/")
    v = v.split("/")[0]
    if v and "." not in v:
        v = f"{v}.myshopify.com"
    return v


def _from_table(key: str, cfg: dict) -> dict | None:
    cfg = {str(k).lower(): v for k, v in dict(cfg).items()}
    shop = next((cfg[k] for k in _SHOP_KEYS if cfg.get(k)), None)
    tok = next((cfg[k] for k in _TOKEN_KEYS if cfg.get(k)), None)
    if not shop:
        return None
    out = {**cfg, "shop": _norm_shop(shop)}
    if tok:
        out["token"] = tok
    out.setdefault("nombre", key.replace("_", " ").title())
    return out


def stores() -> dict[str, dict]:
    """Tiendas Shopify configuradas. Acepta:
    1) tablas [shopify.<clave>] con shop + token (o client_id/client_secret)
    2) los secrets de tus otros repos: TOKEN_REEBOK, TOKEN_COLUMBIA, TOKEN_CROCS, TOKEN_KAPPA, TOKEN_PICCADILLY
       (opcional SHOP_<MARCA> para otro dominio)"""
    out: dict[str, dict] = {}
    raw = secret("shopify", {}) or {}
    try:
        items = dict(raw).items()
    except Exception:  # noqa: BLE001
        items = []
    sueltos = {}
    for key, cfg in items:
        if isinstance(cfg, str):  # [shopify] con TOKEN_KAPPA = "..." adentro
            sueltos[str(key).upper()] = cfg
            continue
        try:
            t = _from_table(key, cfg)
        except Exception:  # noqa: BLE001
            t = None
        if t:
            out[str(key).lower()] = t
    for key, d in DEFAULT_STORES.items():
        if key in out:
            continue
        tok = secret(d["secret"]) or secret(d["secret"].lower()) or sueltos.get(d["secret"]) or sueltos.get(key.upper())
        if tok:
            shop = secret(f"SHOP_{key.upper()}") or d["shop"]
            out[key] = {"shop": _norm_shop(shop), "token": tok, "nombre": d["nombre"], "meli": d["meli"]}
    # Tiendas conectadas con el botón "Conectar tienda" (OAuth): tienen prioridad sobre los secrets
    try:
        from .shopify_auth import get_shopify_auth
        conectadas = get_shopify_auth().connected()
    except Exception:  # noqa: BLE001
        conectadas = {}
    for shop, rec in conectadas.items():
        key = next((k for k, d in DEFAULT_STORES.items() if d["shop"] == shop), shop.split(".")[0])
        base = DEFAULT_STORES.get(key, {})
        out[key] = {
            "shop": shop, "token": rec.get("token"), "oauth": True,
            "nombre": rec.get("nombre") or base.get("nombre") or key,
            "meli": rec.get("meli") or base.get("meli", ""), "vendor": rec.get("vendor", ""),
        }
    # Mountain Hardwear y Sorel: tiendas "virtuales" filtradas por vendor dentro de su tienda
    for vk, d in VENDOR_STORES.items():
        if vk in out:
            continue
        shop = _norm_shop(secret(f"SHOP_{vk.upper()}") or "")
        tok = secret(f"TOKEN_{vk.upper()}")
        if not shop:
            candidatos = [d["shop"]] + [c["shop"] for k_, c in out.items() if k_ == "columbia"]
            shop = next((x for x in candidatos if any(c["shop"] == x for c in out.values())), d["shop"])
        base = next((c for c in out.values() if c["shop"] == shop and not c.get("vendor")), None)
        if tok or base:
            out[vk] = {"shop": shop, "token": tok or base.get("token"), "nombre": d["nombre"], "meli": d["meli"],
                       "vendor": secret(f"VENDOR_{vk.upper()}") or d["vendor"], "virtual": True,
                       **({k_: base[k_] for k_ in ("client_id", "client_secret") if base and base.get(k_)} if not tok else {})}
    for k, c in out.items():
        c["key"] = k
    return out


def secret_names_hint() -> list[str]:
    """Nombres (no valores) de secrets que parecen de Shopify, para diagnosticar configuraciones."""
    try:
        names = list(st.secrets.keys())
    except Exception:  # noqa: BLE001
        return []
    return [n for n in names if re.search(r"shop|token_|myshopify", n, re.I) and n not in
            ("GITHUB_TOKEN", "ANTHROPIC_API_KEY")]


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

    def gql(self, query: str, variables: dict | None = None, retries: int = 6, version: str | None = None) -> dict:
        url = self.url if not version else f"https://{self.shop}/admin/api/{version}/graphql.json"
        force = False
        for attempt in range(retries):
            try:
                r = requests.post(url, json={"query": query, "variables": variables or {}}, timeout=60,
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
                msg = "; ".join(e.get("message", str(e)) for e in errs)[:400]
                if "access" in msg.lower() and ("scope" in msg.lower() or "denied" in msg.lower()):
                    msg += " → Falta un permiso en la app de Shopify: agregalo en el Dev Dashboard y tocá «Conectar tienda» de nuevo."
                raise ShopifyError(f"{self.cfg['nombre']}: {msg}")
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
                         seo { title description } featuredMedia { preview { image { url } } } }
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
            li = re.sub(r'^[-•*·]\s+', '', esc)
            out.append(f"<li>{li}</li>")
            continue
        if lista:
            out.append("</ul>")
            lista = False
        if re.match(r"^P:\s*", line, re.I):
            h3 = re.sub(r'^P:\s*', '', esc, flags=re.I)
            out.append(f"<h3>{h3}</h3>")
        elif re.match(r"^R:\s*", line, re.I):
            pr = re.sub(r'^R:\s*', '', esc, flags=re.I)
            out.append(f"<p>{pr}</p>")
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
