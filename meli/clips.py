"""Clips / video por publicación, con la API oficial de Calidad de publicaciones (/item/{id}/performance).

MeLi incluye en la calidad el objetivo «Creá un video» (el mismo que aparece en Central de vendedores como
«Sin video»). Si ese objetivo está COMPLETED la publicación ya tiene video/clip; si está PENDING, no tiene.
La lectura de la página pública no sirve: MeLi la bloquea desde servidores (verificación de cuenta).
"""
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd

from .api import MeliClient, MeliError
from .catalog import multiget

_VIDEO = re.compile(r"video|clip|short", re.I)


def _reglas(perf: dict) -> list[dict]:
    out = []
    for b in perf.get("buckets") or []:
        for v in b.get("variables") or []:
            for r in v.get("rules") or [{}]:
                w = r.get("wordings") or {}
                out.append({"variable": v.get("key"), "regla": r.get("key"), "estado": r.get("status") or v.get("status"),
                            "titulo": w.get("title") or v.get("title") or "", "label": w.get("label") or "",
                            "link": w.get("link") or ""})
    return out


def video_de(perf: dict) -> tuple[str, str, str]:
    """(situación, regla, link para crear) a partir de la respuesta de /performance."""
    regs = [r for r in _reglas(perf) if _VIDEO.search(" ".join(str(r[k] or "") for k in ("variable", "regla", "titulo", "label")))]
    if not regs:
        return "sin dato", "", ""
    pend = [r for r in regs if r["estado"] == "PENDING"]
    if pend:
        return "sin video", pend[0]["regla"] or pend[0]["variable"], pend[0]["link"]
    return "con video", regs[0]["regla"] or regs[0]["variable"], ""


def performance(client: MeliClient, it: dict) -> tuple[dict, str]:
    iid = it["id"]
    try:
        return client.get(f"/item/{iid}/performance") or {}, ""
    except MeliError as e:
        up = it.get("user_product_id")
        if up and e.status in (400, 404):
            try:
                return client.get(f"/user-product/{up}/performance") or {}, ""
            except MeliError as e2:
                return {}, f"{e2.status}: {str(e2)[:100]}"
        return {}, f"{e.status}: {str(e)[:100]}"


def relevar(client: MeliClient, item_ids: list[str], progress=None, workers: int = 8) -> pd.DataFrame:
    items = {it["id"]: it for it in multiget(client, item_ids)}
    res: dict[str, tuple[dict, str]] = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(performance, client, items[i]): i for i in item_ids if i in items}
        for n, f in enumerate(as_completed(futs), 1):
            res[futs[f]] = f.result()
            if progress:
                progress(n / max(len(futs), 1))
    rows = []
    for iid in item_ids:
        it = items.get(iid, {})
        perf, err = res.get(iid, ({}, "no se pudo leer la publicación"))
        sit, regla, link_crear = video_de(perf) if perf else ("sin dato", "", "")
        pics = it.get("pictures") or []
        rows.append({
            "item_id": iid, "titulo": it.get("title"), "estado_pub": it.get("status"),
            "foto": ((pics[0].get("secure_url") if pics else it.get("thumbnail")) or "").replace("http://", "https://"),
            "vendidos": it.get("sold_quantity") or 0, "stock": it.get("available_quantity"),
            "video": sit, "regla": regla, "crear_link": link_crear, "calidad": perf.get("score"),
            "video_clasico": bool(it.get("video_id")), "link": it.get("permalink"), "error": err,
        })
    return pd.DataFrame(rows)


def diagnostico(client: MeliClient, item_id: str) -> dict:
    it = (multiget(client, [item_id]) or [{}])[0]
    if not it:
        return {"error": "No encontré la publicación en esta cuenta"}
    perf, err = performance(client, it)
    sit, regla, link = video_de(perf) if perf else ("sin dato", "", "")
    return {"publicacion": it.get("title"), "error": err, "calidad": perf.get("score"), "video": sit, "regla_video": regla,
            "reglas_relacionadas": [r for r in _reglas(perf) if _VIDEO.search(f"{r['variable']} {r['regla']} {r['titulo']} {r['label']}")],
            "todas_las_reglas": [f"{r['variable']}/{r['regla']}: {r['estado']}" for r in _reglas(perf)]}
