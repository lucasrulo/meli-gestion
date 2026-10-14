"""Plantillas Excel, lectura tolerante de columnas y parseo de precios en formato AR."""
import io
import re
import unicodedata

import pandas as pd


def _norm_col(c: str) -> str:
    c = unicodedata.normalize("NFKD", str(c)).encode("ascii", "ignore").decode().lower().strip()
    return re.sub(r"[^a-z0-9]+", "_", c).strip("_")


ALIASES = {
    "sku": {"sku", "seller_sku", "codigo", "cod", "articulo", "sku_vendedor"},
    "item_id": {"item_id", "item", "publicacion", "id_publicacion", "mla", "id"},
    "precio": {"precio", "precio_nuevo", "price", "nuevo_precio", "precio_lista"},
    "precio_promo": {"precio_promo", "deal_price", "precio_oferta", "precio_promocion"},
    "descuento_pct": {"descuento_pct", "descuento", "pct", "porcentaje", "dto", "descuento"},
    "precio_meli_plus": {"precio_meli_plus", "top_deal_price", "precio_nivel_6"},
}


def read_excel(file) -> pd.DataFrame:
    name = getattr(file, "name", "").lower()
    df = pd.read_csv(file, dtype=str) if name.endswith(".csv") else pd.read_excel(file, dtype=str)
    rename = {}
    for col in df.columns:
        n = _norm_col(col)
        for target, opts in ALIASES.items():
            if n in opts and target not in rename.values():
                rename[col] = target
                break
    df = df.rename(columns=rename)
    df = df.dropna(how="all")
    return df


def to_number(v) -> float | None:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace("$", "").replace("%", "").replace(" ", "")
    if not s or s.lower() in {"nan", "none"}:
        return None
    if "," in s and "." in s:          # 12.999,50
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:                      # 12999,50
        s = s.replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+", s):  # 12.999 / 1.299.999
        s = s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        return None


def template(columns: list[str], example: list[list]) -> bytes:
    buf = io.BytesIO()
    pd.DataFrame(example, columns=columns).to_excel(buf, index=False)
    return buf.getvalue()


def to_xlsx(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    return buf.getvalue()
