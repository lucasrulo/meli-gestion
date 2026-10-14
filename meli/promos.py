"""Central de promociones de MeLi (seller-promotions, app_version=v2)."""
from datetime import datetime

from .api import MeliClient

V2 = {"app_version": "v2"}

# Tipos que se cargan con un precio (deal_price)
PRICE_TYPES = {"SELLER_CAMPAIGN", "DEAL", "DOD", "LIGHTNING", "PRICE_DISCOUNT"}
# Tipos donde MeLi propone la oferta (se acepta con offer_id)
OFFER_TYPES = {
    "MARKETPLACE_CAMPAIGN", "SMART", "PRICE_MATCHING", "PRICE_MATCHING_MELI_ALL",
    "UNHEALTHY_STOCK", "PRE_NEGOTIATED", "VOLUME", "SELLER_COUPON_CAMPAIGN",
}

TYPE_LABELS = {
    "SELLER_CAMPAIGN": "Campaña propia",
    "PRICE_DISCOUNT": "Descuento individual",
    "DEAL": "Campaña tradicional MeLi",
    "MARKETPLACE_CAMPAIGN": "Co-fondeada MeLi",
    "SMART": "Co-participación automatizada",
    "PRICE_MATCHING": "Precios competitivos",
    "PRICE_MATCHING_MELI_ALL": "Precios competitivos (100% MeLi)",
    "UNHEALTHY_STOCK": "Liquidación stock Full",
    "PRE_NEGOTIATED": "Pre-acordado por item",
    "VOLUME": "Descuento por cantidad",
    "DOD": "Oferta del día",
    "LIGHTNING": "Oferta relámpago",
    "SELLER_COUPON_CAMPAIGN": "Cupón del vendedor",
}


def fmt_date(d: datetime) -> str:
    return d.strftime("%Y-%m-%dT%H:%M:%S")


def list_promotions(client: MeliClient) -> list[dict]:
    out, seen, offset = [], set(), 0
    while True:
        r = client.get(f"/seller-promotions/users/{client.user_id}", params={**V2, "offset": offset, "limit": 50})
        results = r.get("results", []) if isinstance(r, dict) else []
        new = [p for p in results if (p.get("id"), p.get("type")) not in seen]
        if not new:
            break
        for p in new:
            seen.add((p.get("id"), p.get("type")))
        out.extend(new)
        total = (r.get("paging") or {}).get("total")
        offset += len(results)
        if total is None or offset >= total or len(results) < 50:
            break
    return out


def promotion_items(client: MeliClient, promo_id: str, promo_type: str, status: str | None = None,
                    max_pages: int = 400) -> list[dict]:
    params = {**V2, "promotion_type": promo_type, "limit": 50}
    if status:
        params["status"] = status
    out = []
    for _ in range(max_pages):
        r = client.get(f"/seller-promotions/promotions/{promo_id}/items", params=params)
        results = r.get("results", []) if isinstance(r, dict) else []
        out.extend(results)
        nxt = (r.get("paging") or {}).get("searchAfter")
        if not results or not nxt:
            break
        params["search_after"] = nxt
    return out


def create_seller_campaign(client: MeliClient, name: str, start: datetime, finish: datetime) -> dict:
    body = {
        "promotion_type": "SELLER_CAMPAIGN",
        "name": name,
        "sub_type": "FLEXIBLE_PERCENTAGE",
        "start_date": fmt_date(start),
        "finish_date": fmt_date(finish),
    }
    return client.post("/seller-promotions/promotions", json=body, params=V2)


def update_seller_campaign(client: MeliClient, promo_id: str, name: str, start: datetime, finish: datetime) -> dict:
    body = {
        "promotion_type": "SELLER_CAMPAIGN",
        "name": name,
        "start_date": fmt_date(start),
        "finish_date": fmt_date(finish),
    }
    return client.put(f"/seller-promotions/promotions/{promo_id}", json=body, params=V2)


def delete_promotion(client: MeliClient, promo_id: str, promo_type: str = "SELLER_CAMPAIGN") -> dict:
    return client.delete(f"/seller-promotions/promotions/{promo_id}", params={**V2, "promotion_type": promo_type})


def add_item(client: MeliClient, item_id: str, promo_type: str, promo_id: str | None = None,
             deal_price: float | None = None, top_deal_price: float | None = None,
             offer_id: str | None = None, start: datetime | None = None, finish: datetime | None = None,
             stock: int | None = None) -> dict:
    body: dict = {"promotion_type": promo_type}
    if promo_id and promo_type != "PRICE_DISCOUNT":
        body["promotion_id"] = promo_id
    if offer_id and promo_type in OFFER_TYPES:
        body["offer_id"] = offer_id
    if deal_price is not None and promo_type in PRICE_TYPES:
        body["deal_price"] = deal_price
    if top_deal_price:
        body["top_deal_price"] = top_deal_price
    if start:
        body["start_date"] = fmt_date(start)
    if finish:
        body["finish_date"] = fmt_date(finish)
    if stock:
        body["stock"] = int(stock)
    return client.post(f"/seller-promotions/items/{item_id}", json=body, params=V2)


def remove_item(client: MeliClient, item_id: str, promo_type: str, promo_id: str | None = None,
                offer_id: str | None = None) -> dict:
    params = {**V2, "promotion_type": promo_type}
    if promo_id and promo_type != "PRICE_DISCOUNT":
        params["promotion_id"] = promo_id
    if offer_id:
        params["offer_id"] = offer_id
    return client.delete(f"/seller-promotions/items/{item_id}", params=params)


def item_promotions(client: MeliClient, item_id: str) -> list[dict]:
    r = client.get(f"/seller-promotions/items/{item_id}", params=V2)
    return r if isinstance(r, list) else r.get("results", [])
