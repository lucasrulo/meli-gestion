"""URLs de miniaturas livianas para tablas (las fotos originales pesan varios MB y a veces no cargan)."""
import re


def thumb(url: str | None, ancho: int = 300) -> str:
    u = str(url or "").strip()
    if not u or u.lower() in ("nan", "none"):
        return ""
    u = u.replace("http://", "https://")
    if "cdn.shopify.com" in u or "/cdn/shop/" in u:
        u = re.sub(r"([?&])width=\d+", "", u).rstrip("?&")
        return u + ("&" if "?" in u else "?") + f"width={ancho}"
    if "mlstatic.com" in u:   # MeLi: -O / -F (original) → -I (miniatura estándar, cuadrada)
        return re.sub(r"-[OFVWXI](\.(?:jpe?g|webp|png))$", r"-I\1", u)
    return u


def foto_meli(it: dict) -> str:
    """Miniatura de una publicación de MeLi (prioriza la miniatura oficial, siempre cuadrada)."""
    t = it.get("secure_thumbnail") or it.get("thumbnail")
    if not t:
        pics = it.get("pictures") or []
        t = (pics[0].get("secure_url") or pics[0].get("url")) if pics else ""
    return thumb(t)
