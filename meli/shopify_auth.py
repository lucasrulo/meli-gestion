"""Conexión de tiendas Shopify por OAuth (botón "Conectar tienda", como MeLi).

Secrets:
    SHOPIFY_CLIENT_ID = "..."          # app del Dev Dashboard (Client ID)
    SHOPIFY_CLIENT_SECRET = "..."      # (Client secret)
    SHOPIFY_SCOPES = "read_products,write_products,read_inventory"   # opcional
    # Si cada tienda tiene su propia app (tiendas que no son de la misma organización Plus):
    [shopify_apps.kappa-ar]
    client_id = "..."
    client_secret = "..."

Los tokens obtenidos se guardan en shopify_tokens.json en la rama `tokens` del repo (igual que MeLi).
"""
import base64
import hashlib
import hmac
import re
import threading
import time
from urllib.parse import urlencode

import requests
import streamlit as st

from .config import secret
from .token_store import GitHubTokenStore

DEFAULT_SCOPES = ("read_products,write_products,read_inventory,write_files,write_online_store_navigation,"
                  "read_publications,write_publications")
STATE_TTL = 15 * 60


class ShopifyAuthError(Exception):
    pass


def norm_shop(v: str) -> str:
    v = re.sub(r"^https?://", "", str(v or "").strip().lower()).strip("/").split("/")[0]
    if v and "." not in v:
        v += ".myshopify.com"
    return v if re.fullmatch(r"[a-z0-9][a-z0-9\-]*\.myshopify\.com", v or "") else ""


def credentials_for(shop: str) -> tuple[str | None, str | None]:
    sub = shop.split(".")[0]
    apps = secret("shopify_apps", {}) or {}
    try:
        cfg = dict(apps).get(sub) or dict(apps).get(shop)
    except Exception:  # noqa: BLE001
        cfg = None
    if cfg:
        cfg = dict(cfg)
        return cfg.get("client_id"), cfg.get("client_secret")
    return secret("SHOPIFY_CLIENT_ID"), secret("SHOPIFY_CLIENT_SECRET")


def oauth_enabled() -> bool:
    return bool(secret("SHOPIFY_CLIENT_ID") or secret("shopify_apps"))


def _keystream(key: str, n: int, nonce: bytes) -> bytes:
    out, i = b"", 0
    while len(out) < n:
        out += hmac.new(key.encode(), nonce + i.to_bytes(4, "big"), hashlib.sha256).digest()
        i += 1
    return out[:n]


def _enc(token: str, key: str) -> str:
    """Cifra el token antes de guardarlo en GitHub (así no queda en texto plano ni lo bloquea el escaneo de secretos)."""
    import os
    nonce = os.urandom(12)
    raw = token.encode()
    ct = bytes(a ^ b for a, b in zip(raw, _keystream(key, len(raw), nonce)))
    return base64.urlsafe_b64encode(nonce + ct).decode()


def _dec(blob: str, key: str) -> str:
    b = base64.urlsafe_b64decode(blob.encode())
    nonce, ct = b[:12], b[12:]
    return bytes(a ^ c for a, c in zip(ct, _keystream(key, len(ct), nonce))).decode()


def _key_for(shop: str) -> str:
    return secret("TOKENS_KEY") or credentials_for(shop)[1] or ""


class ShopifyAuth:
    def __init__(self):
        self.store = GitHubTokenStore()
        self.store.path = "shopify_tokens.json"
        self.lock = threading.RLock()
        self._data: dict | None = None
        self.redirect_uri = secret("SHOPIFY_REDIRECT_URI") or secret("MELI_REDIRECT_URI")

    # ---------- tiendas conectadas ----------
    def connected(self, reload: bool = False) -> dict:
        with self.lock:
            if self._data is None or reload:
                try:
                    self._data, _ = self.store.load()
                except Exception:  # noqa: BLE001
                    self._data = self._data or {}
            out = {}
            for shop, rec in self._data.items():
                rec = dict(rec)
                if rec.get("token_enc"):
                    try:
                        rec["token"] = _dec(rec["token_enc"], _key_for(shop))
                    except Exception:  # noqa: BLE001
                        rec["token"] = None
                out[shop] = rec
            return out

    def _update(self, fn, msg: str) -> None:
        with self.lock:
            self._data = self.store.update(fn, msg)

    def set_meta(self, shop: str, **meta) -> None:
        def fn(d):
            if shop in d:
                d[shop] = {**d[shop], **meta}
                d[shop].pop("token", None)
            return d
        self._update(fn, f"shopify meta {shop}")

    def remove(self, shop: str) -> None:
        def fn(d):
            d.pop(shop, None)
            return d
        self._update(fn, f"shopify desconectar {shop}")

    # ---------- OAuth ----------
    def _sign(self, payload: str, secret_: str) -> str:
        return hmac.new(secret_.encode(), payload.encode(), hashlib.sha256).hexdigest()

    def authorize_url(self, shop: str) -> str:
        shop = norm_shop(shop)
        cid, csec = credentials_for(shop)
        if not (shop and cid and csec):
            raise ShopifyAuthError("Falta el dominio de la tienda o las credenciales de la app (SHOPIFY_CLIENT_ID/SECRET).")
        ts = str(int(time.time()))
        state = f"{ts}.{self._sign(shop + ts, csec)[:24]}"
        q = {"client_id": cid, "scope": secret("SHOPIFY_SCOPES", DEFAULT_SCOPES),
             "redirect_uri": self.redirect_uri, "state": state}
        return f"https://{shop}/admin/oauth/authorize?{urlencode(q)}"

    def verify_hmac(self, params: dict) -> bool:
        shop = norm_shop(params.get("shop", ""))
        _, csec = credentials_for(shop)
        if not csec or "hmac" not in params:
            return False
        msg = "&".join(f"{k}={v}" for k, v in sorted(params.items()) if k not in ("hmac", "signature"))
        return hmac.compare_digest(self._sign(msg, csec), params["hmac"])

    def valid_state(self, shop: str, state: str) -> bool:
        _, csec = credentials_for(shop)
        try:
            ts, sig = state.split(".", 1)
            return hmac.compare_digest(sig, self._sign(shop + ts, csec)[:24]) and time.time() - int(ts) < STATE_TTL
        except Exception:  # noqa: BLE001
            return False

    def exchange(self, shop: str, code: str) -> dict:
        shop = norm_shop(shop)
        cid, csec = credentials_for(shop)
        r = requests.post(f"https://{shop}/admin/oauth/access_token", timeout=30,
                          json={"client_id": cid, "client_secret": csec, "code": code})
        if r.status_code != 200:
            raise ShopifyAuthError(f"Shopify rechazó el código ({r.status_code}): {r.text[:300]}")
        tok = r.json()
        info = {}
        try:
            q = "{ shop { name myshopifyDomain } }"
            rr = requests.post(f"https://{shop}/admin/api/{secret('SHOPIFY_API_VERSION', '2026-07')}/graphql.json",
                               json={"query": q}, timeout=30,
                               headers={"X-Shopify-Access-Token": tok["access_token"]})
            info = (rr.json().get("data") or {}).get("shop") or {}
        except Exception:  # noqa: BLE001
            pass
        prev = self.connected().get(shop, {})
        rec = {
            "shop": shop, "token_enc": _enc(tok["access_token"], _key_for(shop)), "scope": tok.get("scope"),
            "nombre": prev.get("nombre") or info.get("name") or shop.split(".")[0],
            "meli": prev.get("meli", ""), "vendor": prev.get("vendor", ""),
            "connected_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }

        def fn(d):
            d[shop] = rec
            return d
        self._update(fn, f"shopify conectar {shop}")
        return {**rec, "token": tok["access_token"]}


@st.cache_resource
def get_shopify_auth() -> ShopifyAuth:
    return ShopifyAuth()


def handle_callback() -> None:
    """Llamar al inicio de app.py. Atiende la vuelta de Shopify (?shop=...&code=...) y la instalación (?shop=&hmac=)."""
    qp = {k: st.query_params.get(k) for k in st.query_params.keys()}
    if "shop" not in qp or "hmac" not in qp:
        return
    auth = get_shopify_auth()
    shop = norm_shop(qp.get("shop"))
    if not auth.verify_hmac(qp):
        st.query_params.clear()
        st.session_state["flash"] = "❌ La respuesta de Shopify no pasó la verificación de seguridad (HMAC)."
        st.rerun()
    if "code" in qp:
        st.query_params.clear()
        if qp.get("state") and not auth.valid_state(shop, qp["state"]):
            st.session_state["flash"] = "❌ El link de conexión de Shopify venció. Volvé a tocar Conectar tienda."
        else:
            try:
                rec = auth.exchange(shop, qp["code"])
                st.session_state["flash"] = f"✅ Tienda Shopify conectada: {rec['nombre']} ({shop})"
            except Exception as e:  # noqa: BLE001
                st.session_state["flash"] = f"❌ No se pudo guardar la conexión de {shop}: {e}"
        st.rerun()
    # Entrada desde el link de instalación: pedir autorización
    url = auth.authorize_url(shop)
    st.query_params.clear()
    st.markdown(f'<meta http-equiv="refresh" content="0; url={url}">', unsafe_allow_html=True)
    st.info(f"Conectando la tienda **{shop}**…")
    st.link_button("Autorizar en Shopify", url, type="primary")
    st.stop()
