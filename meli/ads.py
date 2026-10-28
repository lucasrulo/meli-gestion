"""Publicidad MercadoLibre (Product Ads): campañas, métricas y cambios masivos.

Lectura: documentada para Argentina (/advertising/...). Modificar campaña: documentada en Global Selling
(PUT /marketplace/advertising/{site}/product_ads/campaigns/{id}); se prueba primero la ruta local y si no existe, esa.
`automatic_budget` (ajuste automático de presupuesto) se lee de la API; activarlo/desactivarlo es experimental:
después de cada cambio se vuelve a leer la campaña para confirmar si MeLi lo aplicó.
"""
from datetime import date, timedelta

import pandas as pd

from .api import MeliClient, MeliError

V1, V2 = {"Api-Version": "1"}, {"api-version": "2"}
METRICAS = "clicks,prints,ctr,cost,cpc,acos,roas,cvr,units_quantity,total_amount,direct_amount,sov"
ESTRATEGIAS = {"PROFITABILITY": "Rentabilidad", "INCREASE": "Crecimiento", "VISIBILITY": "Visibilidad"}


def anunciante(client: MeliClient) -> dict | None:
    d = client.request("GET", "/advertising/advertisers", params={"product_id": "PADS"}, headers=V1) or {}
    advs = d.get("advertisers") or []
    return advs[0] if advs else None


def campanas(client: MeliClient, site: str, adv_id, dias: int = 30) -> pd.DataFrame:
    hasta = date.today() - timedelta(days=1)
    desde = hasta - timedelta(days=dias - 1)
    rows, offset = [], 0
    while True:
        d = client.request("GET", f"/advertising/{site}/advertisers/{adv_id}/product_ads/campaigns/search", headers=V2,
                           params={"limit": 50, "offset": offset, "date_from": desde.isoformat(),
                                   "date_to": hasta.isoformat(), "metrics": METRICAS}) or {}
        res = d.get("results") or []
        for c in res:
            m = c.get("metrics") or {}
            rows.append({
                "id": c["id"], "nombre": c.get("name"), "estado": c.get("status"),
                "presupuesto": c.get("budget") or c.get("daily_budget"), "ajuste_auto": c.get("automatic_budget"),
                "estrategia": (c.get("strategy") or "").upper(), "roas_objetivo": c.get("roas_target"),
                "acos_objetivo": c.get("acos_target"), "inversion": m.get("cost"), "ventas_$": m.get("total_amount"),
                "unidades": m.get("units_quantity"), "roas": m.get("roas"), "acos": m.get("acos"),
                "clics": m.get("clicks"), "impresiones": m.get("prints"), "ctr": m.get("ctr"), "cvr": m.get("cvr"),
                "moneda": c.get("currency_id"),
            })
        total = (d.get("paging") or {}).get("total", 0)
        offset += 50
        if not res or offset >= total:
            break
    df = pd.DataFrame(rows)
    if not df.empty and df["ajuste_auto"].isna().all():   # el search no lo trae: se lee del detalle
        df["ajuste_auto"] = [detalle(client, site, i).get("automatic_budget") for i in df["id"]]
    return df


def detalle(client: MeliClient, site: str, cid) -> dict:
    try:
        return client.request("GET", f"/advertising/{site}/product_ads/campaigns/{cid}", headers=V2) or {}
    except MeliError:
        return {}


def modificar(client: MeliClient, site: str, cid, cambios: dict) -> dict:
    """PUT de la campaña (ruta local; si no existe, la de Global Selling)."""
    ultimo = None
    for ruta in (f"/advertising/{site}/product_ads/campaigns/{cid}",
                 f"/marketplace/advertising/{site}/product_ads/campaigns/{cid}"):
        try:
            return client.request("PUT", ruta, json=cambios, headers=V2) or {}
        except MeliError as e:
            ultimo = e
            if e.status not in (404, 405):
                raise
    raise ultimo
