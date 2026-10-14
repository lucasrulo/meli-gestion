"""Bloque común de las solapas: cargar listado (pegar o Excel) → buscar → vista previa por modelo-color."""
import pandas as pd
import streamlit as st

from .catalog import MODES, match
from .excel import read_excel, template, to_number, to_xlsx


# ---------------------------------------------------------------- entrada
def _parse_paste(txt: str, kind: str) -> pd.DataFrame:
    rows = []
    for line in txt.splitlines():
        line = line.strip()
        if not line:
            continue
        if "\t" in line:
            parts = [p.strip() for p in line.split("\t")]
        elif ";" in line:
            parts = [p.strip() for p in line.split(";")]
        else:
            parts = line.rsplit(None, 1) if kind != "lista" else [line]
        clave = parts[0]
        val = parts[1] if len(parts) > 1 else ""
        if kind == "lista":
            rows.append({"clave": clave})
            continue
        num = to_number(val)
        if num is None:  # encabezado o línea sin valor
            continue
        if kind == "precio":
            rows.append({"clave": clave, "precio": num})
        else:  # promo: "25%" o "25" (≤90) = descuento; número grande = precio promo
            is_pct = "%" in val or num <= 90
            rows.append({"clave": clave, "precio_promo": None if is_pct else num,
                         "descuento_pct": num if is_pct else None})
    return pd.DataFrame(rows)


def input_block(kind: str, key: str) -> pd.DataFrame | None:
    """kind: 'precio' (clave+precio) | 'promo' (clave+precio_promo/descuento_pct) | 'lista' (solo claves)."""
    ejemplos = {
        "precio": "CL1234-010\t89999\nCL1234-020\t89999\nKP5566-001\t45999",
        "promo": "CL1234-010\t25%\nCL1234-020\t69999\nKP5566-001\t30",
        "lista": "CL1234-010\nKP5566-001",
    }
    ayuda = {
        "precio": "Una fila por modelo-color (o SKU / MLA) y el **precio nuevo**. Copiá las 2 columnas de Excel y pegá.",
        "promo": "Una fila por modelo-color y **% de descuento** (`25%` o `25`) **o precio promo** (`69999`).",
        "lista": "Un modelo-color (o SKU / MLA) por línea.",
    }
    tpl_cols = {"precio": (["modelo_color", "precio"], [["CL1234-010", 89999], ["KP5566-001", 45999]]),
                "promo": (["modelo_color", "precio_promo", "descuento_pct"],
                          [["CL1234-010", None, 25], ["KP5566-001", 45999, None]]),
                "lista": (["modelo_color"], [["CL1234-010"], ["KP5566-001"]])}

    st.markdown(ayuda[kind])
    t1, t2 = st.tabs(["📋 Pegar desde Excel", "📎 Subir Excel"])
    with t1:
        txt = st.text_area("Listado", height=180, placeholder=ejemplos[kind], key=f"paste_{key}",
                           label_visibility="collapsed")
    with t2:
        cols, ex = tpl_cols[kind]
        st.download_button("⬇️ Plantilla", template(cols, ex), file_name=f"plantilla_{kind}.xlsx", key=f"tpl_{key}")
        up = st.file_uploader("Excel", type=["xlsx", "xls", "csv"], key=f"up_{key}", label_visibility="collapsed")

    if up is not None:
        df = read_excel(up)
        if "clave" not in df:
            st.error("El Excel necesita una columna modelo_color (o sku / item_id).")
            st.stop()
    elif txt and txt.strip():
        df = _parse_paste(txt, kind)
    else:
        return None

    if df.empty:
        st.warning("No pude leer filas válidas del listado.")
        st.stop()
    df["clave"] = df["clave"].astype(str).str.strip()
    df = df[df["clave"] != ""].drop_duplicates("clave", keep="last")
    for c in ("precio", "precio_promo", "descuento_pct", "precio_meli_plus"):
        if c in df:
            df[c] = df[c].map(to_number)
    return df


def mode_picker(key: str) -> str:
    return st.radio("Cómo buscar", list(MODES), format_func=MODES.get, horizontal=True, key=f"mode_{key}",
                    help="Se ignoran guiones, espacios y mayúsculas. 'Empieza con' trae todos los talles del modelo-color.")


def resolve(index: pd.DataFrame, data: pd.DataFrame, mode: str) -> pd.DataFrame:
    det = match(index, data["clave"], mode=mode)
    det = det.merge(data, on="clave", how="left")
    det["precio_lista"] = det.apply(
        lambda r: to_number(r.get("precio_original")) or to_number(r.get("precio_actual")), axis=1)
    return det


# ---------------------------------------------------------------- cálculo promos
def compute_promo(det: pd.DataFrame, round_int: bool, quitar: bool = False) -> pd.DataFrame:
    def f(r):
        if not r.get("item_id") or pd.isna(r.get("item_id")):
            return pd.Series({"precio_nuevo": None, "dto_%": None, "valido": False, "obs": "No encontrado"})
        base = r.get("precio_lista")
        if quitar:
            return pd.Series({"precio_nuevo": None, "dto_%": None, "valido": True, "obs": ""})
        pp, pct = to_number(r.get("precio_promo")), to_number(r.get("descuento_pct"))
        if pp is None and pct is not None and base:
            pp = base * (1 - pct / 100)
        if pp is None:
            return pd.Series({"precio_nuevo": None, "dto_%": None, "valido": False, "obs": "Falta precio o %"})
        pp = round(pp) if round_int else round(pp, 2)
        dto = round((1 - pp / base) * 100, 1) if base else None
        if base and pp >= base:
            return pd.Series({"precio_nuevo": pp, "dto_%": dto, "valido": False, "obs": "Precio promo ≥ precio lista"})
        obs = "⚠️ <5%: MeLi puede rechazarlo" if dto is not None and dto < 5 else (
            "⚠️ >70%: revisá" if dto is not None and dto > 70 else "")
        return pd.Series({"precio_nuevo": pp, "dto_%": dto, "valido": True, "obs": obs})

    if det.empty:
        return det
    return pd.concat([det, det.apply(f, axis=1)], axis=1)


def compute_precio(det: pd.DataFrame, round_int: bool, alert: float) -> pd.DataFrame:
    def f(r):
        if not r.get("item_id") or pd.isna(r.get("item_id")):
            return pd.Series({"precio_nuevo": None, "var_%": None, "valido": False, "obs": "No encontrado"})
        new = to_number(r.get("precio"))
        if not new or new <= 0:
            return pd.Series({"precio_nuevo": None, "var_%": None, "valido": False, "obs": "Precio inválido"})
        new = round(new) if round_int else round(new, 2)
        cur = r.get("precio_lista")
        var = round((new / cur - 1) * 100, 1) if cur else None
        obs, ok = "", True
        if cur and new == cur:
            obs, ok = "Sin cambio", False
        elif var is not None and abs(var) > alert:
            obs = f"⚠️ Cambio de {var}%"
        po = r.get("precio_original")
        if po is not None and not pd.isna(po):
            obs = (obs + " · " if obs else "") + "Tiene promo activa"
        return pd.Series({"precio_nuevo": new, "var_%": var, "valido": ok, "obs": obs})

    return pd.concat([det, det.apply(f, axis=1)], axis=1)


# ---------------------------------------------------------------- vista previa
def _rng(s: pd.Series) -> str:
    s = pd.to_numeric(s, errors="coerce").dropna()
    if s.empty:
        return ""
    lo, hi = s.min(), s.max()
    fmt = lambda x: f"${x:,.0f}".replace(",", ".")
    return fmt(lo) if lo == hi else f"{fmt(lo)} – {fmt(hi)}"


def preview(det: pd.DataFrame, key: str, var_col: str) -> pd.DataFrame:
    """Muestra resumen por modelo-color + detalle por SKU + no encontrados.
    Devuelve las publicaciones (una fila por item) a procesar."""
    found = det[det["item_id"].notna()]
    nf = det[det["item_id"].isna()]["clave"].unique().tolist()

    m = st.columns(5)
    m[0].metric("Cargados", det["clave"].nunique())
    m[1].metric("Encontrados", found["clave"].nunique())
    m[2].metric("No encontrados", len(nf))
    m[3].metric("SKUs", found["sku"].nunique() if "sku" in found else 0)
    m[4].metric("Publicaciones", found["item_id"].nunique())

    if found.empty:
        st.error("No se encontró ninguno. Probá otro modo de búsqueda o refrescá el catálogo.")
        st.write(nf)
        st.stop()

    summ = (found.groupby("clave", sort=False)
            .agg(skus=("sku", lambda s: s.dropna().nunique()),
                 publicaciones=("item_id", "nunique"),
                 titulo=("titulo", "first"),
                 precio_actual=("precio_lista", _rng),
                 precio_nuevo=("precio_nuevo", _rng),
                 **({var_col: (var_col, lambda s: ", ".join(sorted({f"{x:g}%" for x in s.dropna()})))}),
                 valido=("valido", "any"),
                 obs=("obs", lambda s: " · ".join(sorted({x for x in s if x}))))
            .reset_index())
    summ.insert(0, "aplicar", summ["valido"])

    st.subheader("Resumen por modelo-color")
    st.caption("Destildá *aplicar* en lo que no quieras tocar.")
    ed = st.data_editor(summ.drop(columns=["valido"]), hide_index=True, width="stretch", key=f"sum_{key}",
                        disabled=[c for c in summ.columns if c != "aplicar"])

    with st.expander(f"🔎 Detalle por SKU ({len(found)})"):
        dcols = [c for c in ["clave", "sku", "titulo", "item_id", "estado", "stock", "precio_actual",
                             "precio_original", "precio_nuevo", var_col, "obs", "permalink"] if c in found]
        st.dataframe(found[dcols], hide_index=True, width="stretch",
                     column_config={"permalink": st.column_config.LinkColumn("link", display_text="ver")})
        st.download_button("⬇️ Detalle Excel", to_xlsx(found[dcols]), file_name="detalle_skus.xlsx",
                           key=f"dl_det_{key}")
    if nf:
        with st.expander(f"❌ No encontrados ({len(nf)})"):
            st.dataframe(pd.DataFrame({"clave": nf}), hide_index=True)
            st.download_button("⬇️ No encontrados", to_xlsx(pd.DataFrame({"clave": nf})),
                               file_name="no_encontrados.xlsx", key=f"dl_nf_{key}")

    chosen = set(ed.loc[ed["aplicar"], "clave"])
    todo = found[found["clave"].isin(chosen) & found["valido"]]
    # misma publicación en dos modelos-color distintos → gana la primera
    conflict = todo.groupby("item_id")["clave"].nunique()
    if (conflict > 1).any():
        st.warning(f"{int((conflict > 1).sum())} publicaciones aparecen en más de un modelo-color; se usa el primero.")
    return todo.drop_duplicates("item_id").reset_index(drop=True)
