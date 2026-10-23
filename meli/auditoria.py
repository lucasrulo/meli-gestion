"""Auditoría de calidad de catálogo Shopify: detecta problemas por producto."""
import pandas as pd

from .shopify import html_to_text

CHECKS = {
    # clave: (texto, gravedad, arreglo automático disponible)
    "sin_fotos": ("Sin fotos", "🔴 Alta", "fotos"),
    "pocas_fotos": ("Menos de 3 fotos", "🟡 Media", "fotos"),
    "alt": ("Fotos sin texto alternativo", "🟡 Media", "alt"),
    "sin_desc": ("Sin descripción", "🔴 Alta", None),
    "desc_corta": ("Descripción corta (< 300 caracteres)", "🟡 Media", None),
    "seo_title": ("Sin SEO title", "🟡 Media", "seo"),
    "seo_desc": ("Sin meta description", "🟡 Media", "seo"),
    "seo_largo": ("SEO title > 70 o meta > 160 caracteres", "⚪ Baja", "seo"),
    "sin_sku": ("Variantes sin SKU", "🔴 Alta", None),
    "sku_dup": ("SKU repetido en otro producto", "🔴 Alta", None),
    "precio_0": ("Variante con precio 0", "🔴 Alta", None),
    "tachado": ("Precio tachado menor o igual al precio", "🔴 Alta", "tachado"),
    "activo_sin_stock": ("Activo y sin stock", "🟡 Media", "unlisted"),
    "sin_peso": ("Variantes sin peso", "🟡 Media", None),
    "sin_barcode": ("Variantes sin código de barras", "⚪ Baja", None),
    "sin_tipo": ("Sin tipo de producto", "⚪ Baja", None),
    "sin_tags": ("Sin tags", "⚪ Baja", None),
    "mayus": ("Título en MAYÚSCULAS", "⚪ Baja", None),
}


def auditar(P: pd.DataFrame, V: pd.DataFrame, M: pd.DataFrame) -> pd.DataFrame:
    rows = []
    vp = V.groupby("product_id")
    alt_vacios = M[M["alt"].fillna("").str.strip() == ""].groupby("product_id").size().to_dict() if not M.empty else {}
    skus = V[V["sku"].fillna("") != ""]
    dup = skus.groupby("sku")["product_id"].nunique()
    dup = set(dup[dup > 1].index)

    def add(r, k, det=""):
        txt, grav, fix = CHECKS[k]
        rows.append({"product_id": r["product_id"], "titulo": r["titulo"], "foto": r["foto"], "estado": r["estado"],
                     "check": k, "problema": txt, "gravedad": grav, "detalle": det, "arreglo": fix})

    for _, r in P.iterrows():
        pid = r["product_id"]
        v = vp.get_group(pid) if pid in vp.groups else V.iloc[0:0]
        if r["n_fotos"] == 0:
            add(r, "sin_fotos")
        elif r["n_fotos"] < 3:
            add(r, "pocas_fotos", f"{r['n_fotos']} foto(s)")
        if alt_vacios.get(pid):
            add(r, "alt", f"{alt_vacios[pid]} foto(s)")
        largo = len(html_to_text(r["descripcion_html"]).strip())
        if largo == 0:
            add(r, "sin_desc")
        elif largo < 300:
            add(r, "desc_corta", f"{largo} caracteres")
        if not r["seo_title"]:
            add(r, "seo_title")
        if not r["seo_description"]:
            add(r, "seo_desc")
        if len(r["seo_title"]) > 70 or len(r["seo_description"]) > 160:
            add(r, "seo_largo", f"{len(r['seo_title'])} / {len(r['seo_description'])}")
        if not v.empty:
            n = int((v["sku"].fillna("") == "").sum())
            if n:
                add(r, "sin_sku", f"{n} de {len(v)}")
            d = sorted(set(v["sku"]) & dup)
            if d:
                add(r, "sku_dup", ", ".join(d[:5]))
            if (v["precio"].fillna(0) <= 0).any():
                add(r, "precio_0")
            bad = v[v["precio_tachado"].notna() & (v["precio_tachado"] <= v["precio"])]
            if not bad.empty:
                add(r, "tachado", f"{len(bad)} variante(s)")
            n = int((v["peso"].fillna(0) <= 0).sum())
            if n:
                add(r, "sin_peso", f"{n} de {len(v)}")
            n = int((v["barcode"].fillna("") == "").sum())
            if n:
                add(r, "sin_barcode", f"{n} de {len(v)}")
        if r["estado"] == "ACTIVE" and (r["stock"] or 0) <= 0:
            add(r, "activo_sin_stock")
        if not r["tipo"]:
            add(r, "sin_tipo")
        if not r["tags"]:
            add(r, "sin_tags")
        t = str(r["titulo"] or "")
        if len(t) > 8 and t.upper() == t and any(c.isalpha() for c in t):
            add(r, "mayus")
    return pd.DataFrame(rows, columns=["product_id", "titulo", "foto", "estado", "check", "problema", "gravedad",
                                       "detalle", "arreglo"])


def puntaje(P: pd.DataFrame, A: pd.DataFrame) -> int:
    """0–100: % de chequeos OK ponderado por gravedad."""
    if P.empty:
        return 100
    peso = {"🔴 Alta": 3, "🟡 Media": 2, "⚪ Baja": 1}
    max_pts = len(P) * sum(peso[g] for _, g, _ in CHECKS.values())
    perd = A["gravedad"].map(peso).sum() if not A.empty else 0
    return int(round(100 * (1 - perd / max_pts)))
