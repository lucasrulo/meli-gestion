"""Clips (videos verticales) de MercadoLibre por publicación.

La API de clips no está habilitada para cuentas de Argentina (solo Global Selling). Pero la página pública de cada
publicación trae los clips que muestra ("shorts"): id, vistas, duración y fecha. Se leen de ahí.
"""
import json
import random
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import requests

from .api import MeliClient
from .catalog import multiget

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/128.0.0.0 Safari/537.36")


def _array(html: str, key: str) -> list | None:
    i = html.find(f'"{key}":[')
    if i < 0:
        return None
    start = i + len(key) + 3
    depth, j, en_str, esc = 0, start, False, False
    while j < len(html):
        c = html[j]
        if en_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                en_str = False
        elif c == '"':
            en_str = True
        elif c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                break
        j += 1
    try:
        return json.loads(html[start:j + 1])
    except Exception:  # noqa: BLE001
        return None


def parse_shorts(html: str) -> list[dict]:
    arr = _array(html, "shorts") or []
    out = []
    for s in arr:
        if not isinstance(s, dict):
            continue
        creado = None
        for k in ("track_vip", "track_intention_to_view"):
            ev = ((s.get(k) or {}).get("melidata_event") or {}).get("event_data") or {}
            creado = creado or ev.get("created_at")
        out.append({"clip_id": s.get("id"), "user_id": s.get("user_id"), "vistas": s.get("views") or 0,
                    "duracion": s.get("video_duration"), "creado": (creado or "")[:10]})
    return out


def clips_publicacion(url: str, intentos: int = 3) -> tuple[list[dict], str]:
    """Lee la página pública de la publicación. Devuelve (clips, error)."""
    if not url:
        return [], "sin link"
    for n in range(intentos):
        try:
            r = requests.get(url, timeout=30, headers={"User-Agent": UA, "Accept-Language": "es-AR,es;q=0.9"})
        except requests.RequestException as e:
            err = str(e)[:120]
        else:
            if r.status_code == 200 and "<html" in r.text[:2000].lower():
                if '"shorts":[' in r.text or "gallery" in r.text:
                    return parse_shorts(r.text), ""
                err = "página sin galería (¿captcha o bloqueo?)"
            else:
                err = f"HTTP {r.status_code}"
            if r.status_code == 404:
                return [], "publicación no encontrada"
        time.sleep(1.5 * (n + 1) + random.random())
    return [], err


def relevar(client: MeliClient, item_ids: list[str], progress=None, workers: int = 4) -> pd.DataFrame:
    items = {it["id"]: it for it in multiget(client, item_ids)}
    res: dict[str, tuple[list, str]] = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(clips_publicacion, (items.get(i) or {}).get("permalink")): i for i in item_ids}
        for n, f in enumerate(as_completed(futs), 1):
            res[futs[f]] = f.result()
            if progress:
                progress(n / len(futs))
    rows = []
    for iid in item_ids:
        it = items.get(iid, {})
        cl, err = res.get(iid, ([], "sin consultar"))
        propios = [c for c in cl if not c["user_id"] or str(c["user_id"]) == str(client.user_id)]
        pics = it.get("pictures") or []
        rows.append({
            "item_id": iid, "titulo": it.get("title"), "estado_pub": it.get("status"),
            "foto": ((pics[0].get("secure_url") if pics else it.get("thumbnail")) or "").replace("http://", "https://"),
            "vendidos": it.get("sold_quantity") or 0, "stock": it.get("available_quantity"),
            "clip_ids": [c["clip_id"] for c in propios], "clips_det": propios, "clips": len(propios),
            "vistas": sum(int(c["vistas"] or 0) for c in propios),
            "ultimo_clip": max((c["creado"] for c in propios if c["creado"]), default=""),
            "clips_otros": len(cl) - len(propios),
            "video_clasico": bool(it.get("video_id")), "link": it.get("permalink"), "error": err,
        })
    return pd.DataFrame(rows)
