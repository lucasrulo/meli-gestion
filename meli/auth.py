"""OAuth de MercadoLibre multi-cuenta + refresh automático de tokens."""
import hashlib
import hmac
import threading
import time
from urllib.parse import urlencode

import requests
import streamlit as st

from .config import API_BASE, SITE_AUTH_URL, TOKEN_URL, secret
from .token_store import GitHubTokenStore

STATE_TTL = 15 * 60  # el link de conexión vale 15 minutos


class AuthError(Exception):
    pass


class TokenManager:
    """Una sola instancia por proceso (st.cache_resource) → evita refreshes en paralelo."""

    def __init__(self):
        self.store = GitHubTokenStore()
        self.lock = threading.RLock()
        self._data: dict | None = None
        self.app_id = str(secret("MELI_APP_ID"))
        self.client_secret = secret("MELI_CLIENT_SECRET")
        self.redirect_uri = secret("MELI_REDIRECT_URI")

    # ---------- cuentas ----------
    def accounts(self, reload: bool = False) -> dict:
        with self.lock:
            if self._data is None or reload:
                self._data, _ = self.store.load()
            return dict(self._data)

    def set_alias(self, user_id: str, alias: str) -> None:
        def fn(d):
            if user_id in d:
                d[user_id]["alias"] = alias
            return d
        with self.lock:
            self._data = self.store.update(fn, f"alias {user_id}")

    def remove(self, user_id: str) -> None:
        def fn(d):
            d.pop(user_id, None)
            return d
        with self.lock:
            self._data = self.store.update(fn, f"desconectar {user_id}")

    # ---------- OAuth ----------
    def _sign(self, payload: str) -> str:
        return hmac.new(self.client_secret.encode(), payload.encode(), hashlib.sha256).hexdigest()[:24]

    def auth_url(self) -> str:
        ts = str(int(time.time()))
        state = f"{ts}.{self._sign(ts)}"
        params = {
            "response_type": "code",
            "client_id": self.app_id,
            "redirect_uri": self.redirect_uri,
            "state": state,
        }
        return f"{SITE_AUTH_URL}?{urlencode(params)}"

    def valid_state(self, state: str) -> bool:
        try:
            ts, sig = state.split(".", 1)
            return hmac.compare_digest(sig, self._sign(ts)) and time.time() - int(ts) < STATE_TTL
        except Exception:
            return False

    def exchange_code(self, code: str) -> dict:
        r = requests.post(
            TOKEN_URL,
            headers={"accept": "application/json", "content-type": "application/x-www-form-urlencoded"},
            data={
                "grant_type": "authorization_code",
                "client_id": self.app_id,
                "client_secret": self.client_secret,
                "code": code,
                "redirect_uri": self.redirect_uri,
            },
            timeout=30,
        )
        if r.status_code != 200:
            raise AuthError(f"MeLi rechazó el código ({r.status_code}): {r.text[:400]}")
        tok = r.json()
        me = requests.get(f"{API_BASE}/users/me", headers={"Authorization": f"Bearer {tok['access_token']}"}, timeout=30)
        me.raise_for_status()
        me = me.json()
        uid = str(me["id"])
        existing = self.accounts().get(uid, {})
        rec = {
            "user_id": uid,
            "nickname": me.get("nickname"),
            "alias": existing.get("alias") or me.get("nickname"),
            "site_id": me.get("site_id"),
            "access_token": tok["access_token"],
            "refresh_token": tok["refresh_token"],
            "expires_at": time.time() + int(tok.get("expires_in", 21600)) - 300,
            "connected_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        self._put(uid, rec, f"conectar {rec['nickname']}")
        return rec

    def _put(self, uid: str, rec: dict, msg: str) -> None:
        def fn(d):
            d[uid] = rec
            return d
        with self.lock:
            self._data = self.store.update(fn, msg)

    # ---------- tokens ----------
    def get_access_token(self, user_id: str, force: bool = False) -> str:
        with self.lock:
            rec = self.accounts().get(user_id)
            if not rec:
                raise AuthError(f"La cuenta {user_id} no está conectada.")
            if not force and rec["expires_at"] > time.time():
                return rec["access_token"]

            # Puede que otra instancia ya lo haya refrescado: releo antes de gastar el refresh_token.
            rec = self.accounts(reload=True).get(user_id) or rec
            if not force and rec["expires_at"] > time.time():
                return rec["access_token"]

            r = requests.post(
                TOKEN_URL,
                headers={"accept": "application/json", "content-type": "application/x-www-form-urlencoded"},
                data={
                    "grant_type": "refresh_token",
                    "client_id": self.app_id,
                    "client_secret": self.client_secret,
                    "refresh_token": rec["refresh_token"],
                },
                timeout=30,
            )
            if r.status_code != 200:
                raise AuthError(
                    f"No pude renovar el token de {rec.get('alias')} ({r.status_code}). "
                    "Volvé a conectar la cuenta en la página Cuentas."
                )
            tok = r.json()
            rec = {
                **rec,
                "access_token": tok["access_token"],
                "refresh_token": tok.get("refresh_token", rec["refresh_token"]),
                "expires_at": time.time() + int(tok.get("expires_in", 21600)) - 300,
            }
            self._put(user_id, rec, f"refresh {rec.get('alias')}")
            return rec["access_token"]


@st.cache_resource
def get_token_manager() -> TokenManager:
    return TokenManager()
