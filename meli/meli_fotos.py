"""Fotos en MercadoLibre: subir una imagen una sola vez y agregarla a muchas publicaciones (ej. tabla de talles)."""
import requests
import streamlit as st

from .api import MeliClient, MeliError

API = "https://api.mercadolibre.com"


def subir_imagen(client: MeliClient, contenido: bytes, filename: str, mime: str) -> str:
    """POST /pictures/items/upload → id de la imagen (se reutiliza en todas las publicaciones)."""
    tok = client.tm.get_access_token(client.user_id)
    r = requests.post(f"{API}/pictures/items/upload", headers={"Authorization": f"Bearer {tok}"},
                      files={"file": (filename, contenido, mime)}, timeout=120)
    if r.status_code not in (200, 201):
        try:
            payload = r.json()
        except Exception:  # noqa: BLE001
            payload = r.text
        raise MeliError(r.status_code, payload)
    return r.json()["id"]


@st.cache_data(ttl=86400, show_spinner=False)
def max_fotos(_client: MeliClient, cat_id: str) -> int:
    try:
        return int((_client.get(f"/categories/{cat_id}").get("settings") or {}).get("max_pictures_per_item") or 12)
    except Exception:  # noqa: BLE001
        return 12


@st.cache_data(ttl=86400, show_spinner=False)
def nombre_categoria(_client: MeliClient, cat_id: str) -> str:
    try:
        c = _client.get(f"/categories/{cat_id}")
        ruta = [p["name"] for p in c.get("path_from_root") or []]
        return " › ".join(ruta[-2:]) if ruta else c.get("name", cat_id)
    except Exception:  # noqa: BLE001
        return cat_id


def estado_fotos(item: dict) -> dict:
    """Foto actual de la publicación (para poder volver atrás)."""
    return {"pictures": [p["id"] for p in item.get("pictures") or []],
            "variations": {str(v["id"]): list(v.get("picture_ids") or []) for v in item.get("variations") or []}}


def poner_fotos(client: MeliClient, item_id: str, estado: dict) -> None:
    body = {"pictures": [{"id": p} for p in estado["pictures"]]}
    if estado.get("variations"):
        body["variations"] = [{"id": int(v), "picture_ids": ids} for v, ids in estado["variations"].items()]
    client.put(f"/items/{item_id}", json=body)


def con_imagen(estado: dict, pic_id: str, posicion: str = "final") -> dict:
    """Estado nuevo con la imagen agregada (al final o como 2da), también en cada variación."""
    def add(lista):
        if pic_id in lista:
            return list(lista)
        return (lista[:1] + [pic_id] + lista[1:]) if posicion == "segunda" and lista else lista + [pic_id]
    return {"pictures": add(estado["pictures"]),
            "variations": {v: add(ids) for v, ids in (estado.get("variations") or {}).items()}}
