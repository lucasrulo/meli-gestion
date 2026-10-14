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


# ---------------------------------------------------------------- tabla de carga (modelo | actual | nuevo)
REDONDEOS = {
    "terminado_999": "Terminado en 999",
    "entero": "Entero",
    "100": "Múltiplo de 100",
    "1000": "Múltiplo de 1.000",
    "no": "Sin redondeo",
}


def redondear(x: float, how: str) -> float:
    if x is None or pd.isna(x):
        return None
    if how == "terminado_999":
        return max(round(x / 1000) * 1000 - 1, 999)
    if how == "100":
        return round(x / 100) * 100
    if how == "1000":
        return round(x / 1000) * 1000
    if how == "entero":
        return round(x)
    return round(x, 2)


def _fmt(x):
    return f"${x:,.0f}".replace(",", ".")


def lookup(index: pd.DataFrame, claves, mode: str) -> pd.DataFrame:
    """Por cada clave: precio de lista actual (el más común), rango si varía, SKUs y publicaciones."""
    claves = [c for c in claves if c]
    if not claves:
        return pd.DataFrame(columns=["clave", "precio_actual", "skus", "publicaciones", "estado"])
    det = match(index, claves, mode=mode)
    det["precio_lista"] = det.apply(
        lambda r: to_number(r.get("precio_original")) or to_number(r.get("precio_actual")), axis=1)
    rows = []
    for c in claves:
        d = det[(det["clave"] == c) & det["item_id"].notna()]
        if d.empty:
            rows.append({"clave": c, "precio_actual": None, "skus": 0, "publicaciones": 0,
                         "estado": "❌ No encontrado"})
            continue
        pl = d.drop_duplicates("item_id")["precio_lista"].dropna()
        if pl.empty:
            actual = None
        else:
            vc = pl.value_counts()
            actual = float(vc[vc == vc.max()].index.max())  # el más común; si empatan, el mayor
        estado = "✅"
        if pl.nunique() > 1:
            estado = f"⚠️ Precios distintos {_fmt(pl.min())} – {_fmt(pl.max())}"
        en_promo = d["precio_original"].notna().any() if "precio_original" in d else False
        if en_promo:
            venta = pd.to_numeric(d["precio_actual"], errors="coerce").min()
            estado += f" · en promo ({_fmt(venta)})"
        rows.append({"clave": c, "precio_actual": actual, "skus": int(d["sku"].dropna().nunique()),
                     "publicaciones": int(d["item_id"].nunique()), "estado": estado})
    return pd.DataFrame(rows)


def grid_block(kind: str, key: str, index: pd.DataFrame, mode: str) -> pd.DataFrame | None:
    """Tabla editable: modelo-color | precio actual (lo trae MeLi) | precio nuevo / promo.
    kind: 'precio' | 'promo' | 'lista'. Devuelve DataFrame (clave + precio / precio_promo) listo para resolve()."""
    ss = st.session_state
    key = f"{key}_{kind}"
    newcol = {"precio": "precio", "promo": "precio_promo", "lista": None}[kind]
    newlabel = {"precio": "Precio nuevo", "promo": "Precio promo", "lista": None}[kind]
    sk, vk, lk = f"grid_{key}", f"gridv_{key}", f"gridlook_{key}"
    ss.setdefault(vk, 0)

    def empty(n=15):
        d = pd.DataFrame({"clave": pd.Series([None] * n, dtype="string"),
                          "precio_actual": pd.Series([None] * n, dtype="float")})
        if newcol:
            d[newcol] = pd.Series([None] * n, dtype="float")
        d["skus"] = pd.Series([None] * n, dtype="float")
        d["publicaciones"] = pd.Series([None] * n, dtype="float")
        d["estado"] = pd.Series([None] * n, dtype="string")
        return d

    def store(df):
        ss[sk] = df.reset_index(drop=True)
        ss[vk] += 1
        st.rerun()

    ss.setdefault(sk, empty())

    # ---- pegar lista larga / Excel → carga la tabla
    with st.expander("📋 Pegar lista larga o subir Excel", expanded=ss[sk]["clave"].dropna().empty):
        st.caption("Columna 1: modelo-color / SKU / MLA. Columna 2 (opcional): "
                   + (f"{newlabel.lower()}." if newcol else "no hace falta."))
        a, b = st.columns(2)
        txt = a.text_area("Pegar", height=150, key=f"paste_{key}", label_visibility="collapsed",
                          placeholder="CL1234-010\t89999\nCL1234-020\nKP5566-001")
        up = b.file_uploader("Excel", type=["xlsx", "xls", "csv"], key=f"up_{key}", label_visibility="collapsed")
        if b.button("⬇️ Cargar en la tabla", key=f"load_{key}", type="primary"):
            rows = []
            if up is not None:
                x = read_excel(up)
                if "clave" not in x:
                    st.error("El Excel necesita una columna modelo_color (o sku / item_id).")
                    st.stop()
                valcol = next((c for c in ("precio", "precio_promo") if c in x), None)
                for _, r in x.iterrows():
                    rows.append({"clave": str(r["clave"]).strip(),
                                 "nuevo": to_number(r.get(valcol)) if valcol else None})
            for line in (txt or "").splitlines():
                parts = [p.strip() for p in (line.split("\t") if "\t" in line else line.split(";"))]
                if parts and parts[0]:
                    rows.append({"clave": parts[0], "nuevo": to_number(parts[1]) if len(parts) > 1 else None})
            rows = [r for r in rows if r["clave"] and r["clave"].lower() not in {"nan", "modelo_color", "sku", "modelo"}]
            if not rows:
                st.warning("No hay filas para cargar.")
            else:
                new = pd.DataFrame(rows).drop_duplicates("clave", keep="last")
                df = empty(0)
                df = pd.concat([df, pd.DataFrame({"clave": new["clave"]})], ignore_index=True)
                if newcol:
                    df[newcol] = new["nuevo"].values
                ss.pop(lk, None)
                store(df)

    # ---- tabla editable
    cfg = {
        "clave": st.column_config.TextColumn("Modelo-color / SKU", width="medium"),
        "precio_actual": st.column_config.NumberColumn("Precio actual", format="localized", disabled=True),
        "skus": st.column_config.NumberColumn("SKUs", disabled=True, width="small"),
        "publicaciones": st.column_config.NumberColumn("Publ.", disabled=True, width="small"),
        "estado": st.column_config.TextColumn("Estado", disabled=True, width="large"),
    }
    if newcol:
        cfg[newcol] = st.column_config.NumberColumn(newlabel, format="localized", min_value=0)
    order = ["clave", "precio_actual"] + ([newcol] if newcol else []) + ["skus", "publicaciones", "estado"]
    ed = st.data_editor(ss[sk][order], num_rows="dynamic", hide_index=True, width="stretch",
                        column_config=cfg, key=f"ed_{key}_{ss[vk]}")
    ed = ed.copy()
    ed["clave"] = ed["clave"].astype("string").str.strip()

    # ---- busca precios automáticamente cuando cambian los modelos o el modo de búsqueda
    claves = [c for c in ed["clave"].dropna().tolist() if c]
    sig = (tuple(claves), mode, len(index))
    if claves and ss.get(lk) != sig:
        with st.spinner("Buscando precios actuales…"):
            info = lookup(index, claves, mode).drop_duplicates("clave")
        base = ed[ed["clave"].fillna("") != ""].drop(columns=["precio_actual", "skus", "publicaciones", "estado"])
        base = base.drop_duplicates("clave", keep="last").merge(info, on="clave", how="left")
        ss[lk] = sig
        store(base)

    # ---- acciones masivas
    if newcol:
        st.markdown("**Aplicar a todos**")
        c1, c2, c3, c4 = st.columns([1.2, 1.4, 1.2, 1])
        if kind == "precio":
            pct = c1.number_input("Aumento %", value=10.0, step=5.0, key=f"pct_{key}",
                                  help="Negativo para bajar. Se calcula sobre el precio actual.")
        else:
            pct = c1.number_input("Descuento %", value=20.0, min_value=0.0, max_value=95.0, step=5.0, key=f"pct_{key}")
        how = c2.selectbox("Redondeo", list(REDONDEOS), format_func=REDONDEOS.get, key=f"rnd_{key}")
        solo_vacios = c3.checkbox("Solo filas vacías", key=f"sv_{key}",
                                  help="No pisa los precios que ya cargaste a mano.")
        if c4.button("Aplicar %", key=f"ap_{key}", width="stretch"):
            df = ed[ed["clave"].fillna("") != ""].copy()
            factor = 1 + pct / 100 if kind == "precio" else 1 - pct / 100
            calc = df["precio_actual"].map(lambda v: redondear(v * factor, how) if v and not pd.isna(v) else None)
            mask = df[newcol].isna() if solo_vacios else pd.Series(True, index=df.index)
            df.loc[mask, newcol] = calc[mask]
            store(df)

    b1, b2, _ = st.columns([1, 1, 3])
    if b1.button("🔄 Volver a buscar", key=f"rl_{key}"):
        ss.pop(lk, None)
        store(ed[ed["clave"].fillna("") != ""])
    if b2.button("🗑️ Limpiar tabla", key=f"clr_{key}"):
        ss.pop(lk, None)
        store(empty())

    data = ed[ed["clave"].fillna("") != ""].copy()
    if data.empty:
        return None
    data["clave"] = data["clave"].astype(str)
    keep = ["clave"] + ([newcol] if newcol else [])
    data = data[keep].drop_duplicates("clave", keep="last")
    if newcol:
        data[newcol] = pd.to_numeric(data[newcol], errors="coerce")
        data = data[data[newcol].notna()]
        if data.empty:
            st.info(f"Completá la columna **{newlabel}** (a mano o con *Aplicar %*) para ver la vista previa.")
            return None
    return data
