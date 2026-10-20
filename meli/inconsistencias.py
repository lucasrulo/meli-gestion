"""Detecta un mismo artículo publicado con precios distintos dentro de la cuenta."""
import re
import pandas as pd

from .excel import to_number

AGRUPAR = {
    "auto": "Automático (publicación + color; si no hay datos de publicación, modelo-color por SKU)",
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


_TALLE = re.compile(r"^(\d{1,2}([.,]5)?|\d{1,2}/\d{1,2}|X{0,3}S|S|M|L|X{1,4}L|\d?XL|XXXL|U|UN|UNI|TU|OS|"
                    r"\d{1,2}[A-Z]|[A-Z]\d{1,2})$")


def strip_size(sku) -> str | None:
    """SKU → modelo-color (sin el talle).
    'K1342233W-KSA02-40' → 'K1342233W-KSA02' (2+ guiones: saca el último segmento)
    'P14313300000310SS25-40' → 'P14313300000310SS25' (1 guion: lo saca solo si el último segmento parece talle)."""
    if sku is None or (isinstance(sku, float) and pd.isna(sku)):
        return None
    s = str(sku).strip().upper()
    if "-" not in s:
        return s
    base, last = s.rsplit("-", 1)
    if s.count("-") >= 2 or _TALLE.match(last):
        return base
    return s


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


def _fam_key(df: pd.DataFrame, con_color: bool) -> pd.Series:
    fam = df["familia"].fillna("")
    key = fam + " · " + df["categoria"].fillna("")
    if con_color:
        key = key + " · " + df["color"].fillna("")
    return key.where(fam != "", None)


def group_key(df: pd.DataFrame, how: str) -> pd.Series:
    if how == "auto":
        fam = _fam_key(df, True)
        sku = ("SKU · " + df["modelo_color"].fillna("")).where(df["modelo_color"].notna(), None)
        key = fam.where(fam.notna(), sku)
    elif how == "modelo_color":
        key = df["modelo_color"]
    else:
        key = _fam_key(df, how == "familia_color")
    if "cuenta" in df:  # nunca mezclar cuentas en un mismo grupo
        key = key.where(key.isna(), df["cuenta"].astype(str) + " · " + key.astype(str))
    return key


CAMPOS = {
    "precio_lista": "Precio de lista (sin promo)",
    "precio_venta": "Precio de venta (lo que ve el comprador, con promo)",
}


def find_groups(items: pd.DataFrame, how: str, min_diff_pct: float, texto: str = "",
                estados=("active", "paused"), campo: str = "precio_lista") -> tuple[pd.DataFrame, pd.DataFrame]:
    df = items[items["estado"].isin(estados)].copy()
    df["precio_cmp"] = pd.to_numeric(df[campo], errors="coerce")
    df["grupo"] = group_key(df, how)
    df = df[df["grupo"].notna() & df["precio_cmp"].notna()]
    if texto:
        t = texto.strip().lower()
        df = df[df["titulo"].fillna("").str.lower().str.contains(t, regex=False)
                | df["skus"].fillna("").str.lower().str.contains(t, regex=False)
                | df["grupo"].fillna("").str.lower().str.contains(t, regex=False)]
    g = df.drop_duplicates(["grupo", "item_id"]).groupby("grupo")
    extra = {"cuenta": ("cuenta", "first")} if "cuenta" in df else {}
    summ = g.agg(
        **extra,
        titulo=("titulo", "first"),
        publicaciones=("item_id", "nunique"),
        min=("precio_cmp", "min"),
        max=("precio_cmp", "max"),
        precios_distintos=("precio_cmp", "nunique"),
        moda=("precio_cmp", lambda s: float(s.value_counts().sort_index(ascending=False).idxmax())),
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
    return det.groupby("grupo")["precio_cmp"].apply(fmt)


def objetivo(summ: pd.DataFrame, regla: str) -> pd.Series:
    if regla == "max":
        return summ["max"]
    if regla == "min":
        return summ["min"]
    if regla == "moda":
        return summ["moda"]
    return pd.Series([None] * len(summ), index=summ.index, dtype="float")


def diagnostico(items: pd.DataFrame, how: str, q: str) -> pd.DataFrame:
    """Para entender por qué un artículo no aparece: muestra cómo quedó agrupada cada publicación."""
    t = q.strip().lower()
    df = items[items["titulo"].fillna("").str.lower().str.contains(t, regex=False)
               | items["skus"].fillna("").str.lower().str.contains(t, regex=False)
               | items["item_id"].fillna("").str.lower().str.contains(t, regex=False)].copy()
    df["grupo"] = group_key(df, how)
    cols = [c for c in ["cuenta", "item_id", "titulo", "estado", "skus", "familia", "color", "modelo_color", "grupo",
                        "precio_lista", "precio_venta", "en_promo", "permalink"] if c in df]
    return df[cols].sort_values(["grupo", "precio_lista"], na_position="last").head(300)
