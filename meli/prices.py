"""Actualización de precio de publicaciones."""
from .api import MeliClient


def update_price(client: MeliClient, item_id: str, price: float, variation_ids: str | None = None) -> dict:
    """Items con variaciones (modelo viejo): MeLi exige el mismo precio en todas → se mandan todas.
    Items sin variaciones o User Products: PUT directo de price."""
    vids = [v.strip() for v in str(variation_ids or "").split(",") if v.strip().isdigit()]
    if vids:
        body = {"variations": [{"id": int(v), "price": price} for v in vids]}
    else:
        body = {"price": price}
    return client.put(f"/items/{item_id}", json=body)
