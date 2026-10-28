"""Cliente HTTP de MeLi con refresh automático, reintentos y errores legibles."""
import time

import requests

from .auth import TokenManager
from .config import API_BASE


class MeliError(Exception):
    def __init__(self, status: int, payload):
        self.status = status
        self.payload = payload
        super().__init__(self._format())

    def _format(self) -> str:
        p = self.payload
        if not isinstance(p, dict):
            return f"{self.status}: {str(p)[:400]}"
        parts = [str(p.get("error") or ""), str(p.get("message") or "")]
        causes = p.get("cause") or p.get("causes") or []
        if isinstance(causes, list):
            for c in causes:
                if isinstance(c, dict):
                    parts.append(str(c.get("message") or c.get("code") or c))
                else:
                    parts.append(str(c))
        txt = " | ".join(x for x in parts if x and x != "None")
        return f"{self.status}: {txt or p}"


def _json(r: requests.Response):
    if r.status_code == 204 or not r.content:
        return {}
    try:
        return r.json()
    except ValueError:
        return r.text


class MeliClient:
    def __init__(self, tm: TokenManager, user_id: str):
        self.tm = tm
        self.user_id = str(user_id)

    def request(self, method: str, path: str, params=None, json=None, retries: int = 5, headers: dict | None = None):
        forced = False
        for attempt in range(retries):
            token = self.tm.get_access_token(self.user_id, force=forced)
            forced = False
            try:
                r = requests.request(
                    method,
                    f"{API_BASE}{path}",
                    params=params,
                    json=json,
                    headers={"Authorization": f"Bearer {token}", "Accept": "application/json", **(headers or {})},
                    timeout=40,
                )
            except requests.RequestException as e:
                if attempt == retries - 1:
                    raise MeliError(0, str(e))
                time.sleep(2 ** attempt)
                continue

            if r.status_code == 401 and attempt < retries - 1:
                forced = True
                continue
            if (r.status_code == 429 or r.status_code >= 500) and attempt < retries - 1:
                time.sleep(min(2 ** attempt, 20))
                continue
            if r.status_code >= 400:
                raise MeliError(r.status_code, _json(r))
            return _json(r)
        raise MeliError(0, "Sin respuesta tras reintentos")

    def get(self, path, params=None):
        return self.request("GET", path, params=params)

    def post(self, path, json=None, params=None):
        return self.request("POST", path, params=params, json=json)

    def put(self, path, json=None, params=None):
        return self.request("PUT", path, params=params, json=json)

    def delete(self, path, params=None):
        return self.request("DELETE", path, params=params)
