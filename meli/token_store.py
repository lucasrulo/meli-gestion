"""Guarda los tokens de MeLi en un JSON dentro de una rama aparte del MISMO repo.

Se usa una rama separada (por defecto `tokens`) para que cada refresh de token
NO dispare un redeploy de Streamlit Cloud, que solo mira la rama principal.
Requiere un GitHub fine-grained token con permiso Contents: Read and write
sobre este repo. El repo debe ser PRIVADO.
"""
import base64
import json

import requests

from .config import secret

GH_API = "https://api.github.com"


class TokenStoreError(Exception):
    pass


class _Conflict(Exception):
    pass


class GitHubTokenStore:
    def __init__(self, path: str | None = None):
        self.repo = secret("GITHUB_REPO")
        self.branch = secret("TOKENS_BRANCH", "tokens")
        self.path = path or secret("TOKENS_PATH", "tokens.json")
        self.headers = {
            "Authorization": f"Bearer {secret('GITHUB_TOKEN')}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    # ---------- helpers ----------
    def _url(self, suffix: str) -> str:
        return f"{GH_API}/repos/{self.repo}{suffix}"

    def _ensure_branch(self) -> None:
        r = requests.get(self._url(f"/git/ref/heads/{self.branch}"), headers=self.headers, timeout=20)
        if r.status_code == 200:
            return
        if r.status_code != 404:
            raise TokenStoreError(f"GitHub {r.status_code}: {r.text[:300]}")
        repo = requests.get(self._url(""), headers=self.headers, timeout=20)
        if repo.status_code != 200:
            raise TokenStoreError(f"No pude leer el repo {self.repo}: {repo.status_code} {repo.text[:300]}")
        default_branch = repo.json()["default_branch"]
        ref = requests.get(self._url(f"/git/ref/heads/{default_branch}"), headers=self.headers, timeout=20)
        ref.raise_for_status()
        sha = ref.json()["object"]["sha"]
        c = requests.post(
            self._url("/git/refs"),
            headers=self.headers,
            json={"ref": f"refs/heads/{self.branch}", "sha": sha},
            timeout=20,
        )
        if c.status_code not in (201, 422):  # 422 = ya existe (carrera)
            raise TokenStoreError(f"No pude crear la rama {self.branch}: {c.status_code} {c.text[:300]}")

    # ---------- API pública ----------
    def load(self) -> tuple[dict, str | None]:
        r = requests.get(
            self._url(f"/contents/{self.path}"),
            headers=self.headers,
            params={"ref": self.branch},
            timeout=20,
        )
        if r.status_code == 404:
            return {}, None
        if r.status_code != 200:
            raise TokenStoreError(f"GitHub {r.status_code}: {r.text[:300]}")
        body = r.json()
        content = base64.b64decode(body["content"]).decode("utf-8")
        return (json.loads(content) if content.strip() else {}), body["sha"]

    def _save(self, data: dict, sha: str | None, message: str) -> None:
        self._ensure_branch()
        payload = {
            "message": message,
            "content": base64.b64encode(json.dumps(data, indent=2, ensure_ascii=False).encode()).decode(),
            "branch": self.branch,
        }
        if sha:
            payload["sha"] = sha
        r = requests.put(self._url(f"/contents/{self.path}"), headers=self.headers, json=payload, timeout=20)
        if r.status_code in (409, 422):
            raise _Conflict(r.text)
        if r.status_code not in (200, 201):
            raise TokenStoreError(f"GitHub {r.status_code}: {r.text[:300]}")

    def update(self, fn, message: str) -> dict:
        """Lee → aplica fn(data) → guarda. Reintenta si otro proceso escribió en el medio."""
        for _ in range(4):
            data, sha = self.load()
            new = fn(dict(data))
            try:
                self._save(new, sha, message)
                return new
            except _Conflict:
                continue
        raise TokenStoreError("Conflicto repetido guardando tokens en GitHub, probá de nuevo.")
