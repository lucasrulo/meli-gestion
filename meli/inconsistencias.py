"""Detecta un mismo artículo publicado con precios distintos dentro de la cuenta."""
import pandas as pd

from .excel import to_number

AGRUPAR = {
    "familia_color": "Publicación + color (talles de un mismo color)",
    "familia": "Publicación completa (todos los colores)",
    "modelo_color": "Modelo-color por SKU (SKU sin el talle)",
}
REGLAS = {
    "max": "Igualar al MAYOR precio",
    "min": "Igualar al MENOR precio",
    "moda": "Igualar al MÁS FRECUENTE",
    "manual": "Elegir a mano",
}


def strip_size(sku) -> str | None:
    """'K1342233W-KSA02-40' → 'K1342233W-KSA02'. Con un solo guion o sin guiones deja el SKU igual."""
    if sku is None or (isinstance(sku, float) and pd.isna(sku)):
        return None
    s = str(sku).strip().upper()
    return s.rsplit("-", 1)[0] if s.count("-") >= 2 else s


def items_table(index: pd.DataFrame) -> pd.DataFrame:
    """Una fila por publicación (y por modelo-color si una publicación vieja con variaciones tiene varios)."""
    df = index.copy()
    for c in ("familia", "categoria", "color"):
        if c not in df:
            df[c] = None
    df["modelo_color"] = df["sku"].map(strip_size)
    df["precio_lista"] = df.apply(
        lambda r: to_number(r.get("precio_original")) or to_number(r.get("precio_actual")), axis=1)
    agg = (df.groupby(["item_id", "modelo_color"], dropna=False)
           .agg(titulo=("titulo", "first"), estado=("estado", "first"), precio_lista=("precio_lista", "first"),
                precio_venta=("precio_actual", "first"), precio_original=("precio_original", "first"),
                familia=("familia", "first"), categoria=("categoria", "first"), color=("color", "first"),
                variation_ids=("variation_ids", "first"), stock=("stock", "first"),
                skus=("sku", lambda s: ", ".join(sorted({str(x) for x in s if x}))[:80]),
                permalink=("permalink", "first"))
           .reset_index())
    agg["en_promo"] = agg["precio_original"].notna()
    return agg


def group_key(df: pd.DataFrame, how: str) -> pd.Series:
    if how == "modelo_color":
        return df["modelo_color"]
    fam = df["familia"].fillna("")
    key = fam + " · " + df["categoria"].fillna("")
    if how == "familia_color":
        key = key + " · " + df["color"].fillna("")
    return key.where(fam != "", None)


def find_groups(items: pd.DataFrame, how: str, min_diff_pct: float, texto: str = "",
                estados=("active", "paused")) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = items[items["estado"].isin(estados)].copy()
    df["grupo"] = group_key(df, how)
    df = df[df["grupo"].notna() & df["precio_lista"].notna()]
    if texto:
        t = texto.strip().lower()
        df = df[df["titulo"].fillna("").str.lower().str.contains(t, regex=False)
                | df["skus"].fillna("").str.lower().str.contains(t, regex=False)
                | df["grupo"].fillna("").str.lower().str.contains(t, regex=False)]
    g = df.drop_duplicates(["grupo", "item_id"]).groupby("grupo")
    summ = g.agg(
        titulo=("titulo", "first"),
        publicaciones=("item_id", "nunique"),
        min=("precio_lista", "min"),
        max=("precio_lista", "max"),
        precios_distintos=("precio_lista", "nunique"),
        moda=("precio_lista", lambda s: float(s.value_counts().sort_index(ascending=False).idxmax())),
        en_promo=("en_promo", "sum"),
    ).reset_index()
    summ = summ[summ["precios_distintos"] > 1]
    summ["dif_%"] = ((summ["max"] / summ["min"] - 1) * 100).round(1)
    summ = summ[summ["dif_%"] >= min_diff_pct].sort_values("dif_%", ascending=False)
    det = df[df["grupo"].isin(summ["grupo"])].drop_duplicates(["grupo", "item_id"])
    return summ.reset_index(drop=True), det.reset_index(drop=True)


def precios_texto(det: pd.DataFrame) -> pd.Series:
    def fmt(s):
        vc = s.value_counts().sort_index()
        return " / ".join(f"${v:,.0f}".replace(",", ".") + (f" ×{n}" if n > 1 else "") for v, n in vc.items())
    return det.groupby("grupo")["precio_lista"].apply(fmt)


def objetivo(summ: pd.DataFrame, regla: str) -> pd.Series:
    if regla == "max":
        return summ["max"]
    if regla == "min":
        return summ["min"]
    if regla == "moda":
        return summ["moda"]
    return pd.Series([None] * len(summ), index=summ.index, dtype="float")
