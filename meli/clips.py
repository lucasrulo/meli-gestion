"""Clips (videos verticales) de MercadoLibre por publicación.

MeLi documenta el recurso de clips en Global Selling (/marketplace/items/{id}/clips). Para cuentas locales se prueba
ese recurso y, si no responde, /items/{id}/clips. El que funcione se usa para toda la cuenta.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd

from .api import MeliClient, MeliError
from .catalog import multiget

ENDPOINTS = ["/marketplace/items/{id}/clips", "/items/{id}/clips"]
ESTADOS = {"PUBLISHED": "publicado", "UNDER_REVIEW": "en revisión", "REJECTED": "rechazado",
           "TRANSCODING_REJECTED": "rechazado (video)", "PAUSED": "pausado"}


def _parse(body) -> list[dict]:
    """Normaliza la respuesta a [{clip_uuid, estado, motivo}] (acepta las variantes de formato conocidas)."""
    if isinstance(body, list):
        clips = body
    elif isinstance(body, dict):
        clips = body.get("clips") or body.get("results") or []
    else:
        clips = []
    out = []
    for c in clips:
        meta = c.get("metadata") or [{}]
        m = meta[0] if isinstance(meta, list) and meta else (meta if isinstance(meta, dict) else {})
        est = (m.get("moderation_status") or c.get("moderation_status") or c.get("status") or "").upper()
        mot = m.get("moderation_reasons") or c.get("moderation_reasons") or ""
        if isinstance(mot, list):
            mot = ", ".join(str(x.get("description") or x.get("reason") or x) if isinstance(x, dict) else str(x) for x in mot)
        out.append({"clip_uuid": c.get("clip_uuid") or c.get("id"), "estado": est, "motivo": str(mot)})
    return out


def detectar_endpoint(client: MeliClient, item_ids: list[str]) -> tuple[str | None, list[str]]:
    """Prueba los endpoints sobre algunas publicaciones. Devuelve (endpoint, log de pruebas)."""
    log = []
    for ep in ENDPOINTS:
        for iid in item_ids[:6]:
            try:
                client.get(ep.format(id=iid))
                log.append(f"✅ {ep.format(id=iid)} → 200")
                return ep, log
            except MeliError as e:
                log.append(f"✖ {ep.format(id=iid)} → {e.status}: {str(e)[:120]}")
                if e.status in (401, 403):
                    break
    return None, log


def clips_de(client: MeliClient, ep: str, iid: str) -> tuple[list[dict], str]:
    try:
        return _parse(client.get(ep.format(id=iid))), ""
    except MeliError as e:
        if e.status == 404:
            return [], ""
        return [], f"{e.status}: {str(e)[:150]}"


def relevar(client: MeliClient, item_ids: list[str], ep: str | None, progress=None) -> pd.DataFrame:
    """Por publicación: clips por estado + video clásico + ventas."""
    items = {it["id"]: it for it in multiget(client, item_ids)}
    res: dict[str, tuple[list, str]] = {}
    if ep:
        with ThreadPoolExecutor(max_workers=6) as ex:
            futs = {ex.submit(clips_de, client, ep, i): i for i in item_ids}
            for n, f in enumerate(as_completed(futs), 1):
                res[futs[f]] = f.result()
                if progress:
                    progress(n / len(futs))
    rows = []
    for iid in item_ids:
        it = items.get(iid, {})
        cl, err = res.get(iid, ([], "sin consultar"))
        cuenta = lambda *s: sum(1 for c in cl if c["estado"] in s)  # noqa: E731
        pics = it.get("pictures") or []
        rows.append({
            "item_id": iid, "titulo": it.get("title"), "estado_pub": it.get("status"),
            "foto": ((pics[0].get("secure_url") if pics else it.get("thumbnail")) or "").replace("http://", "https://"),
            "vendidos": it.get("sold_quantity") or 0, "stock": it.get("available_quantity"),
            "clips": len(cl), "publicados": cuenta("PUBLISHED"), "en_revision": cuenta("UNDER_REVIEW"),
            "rechazados": cuenta("REJECTED", "TRANSCODING_REJECTED"), "pausados": cuenta("PAUSED"),
            "motivos": " | ".join(c["motivo"] for c in cl if c["motivo"])[:300],
            "video_clasico": bool(it.get("video_id")), "link": it.get("permalink"), "error": err,
        })
    return pd.DataFrame(rows)
