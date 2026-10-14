"""Manejo del error de MeLi ERROR_CREDIBILITY_DISCOUNTED_PRICE ("precio no creíble").

Después de una carga, guarda el resultado en session_state y, para las filas rechazadas por
credibilidad, consulta a MeLi el rango de precio permitido por publicación y ofrece reintentar
con el máximo permitido.
"""
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import streamlit as st

from . import promos
from .api import MeliClient, MeliError
from .bulk import run_bulk
from .excel import to_number, to_xlsx

CRED = "CREDIBILITY"


def is_cred(err) -> bool:
    return CRED in str(err or "").upper()


def price_limits(client: MeliClient, item_id: str, promo_id: str | None, ptype: str) -> dict:
    """Busca en las promos del item los límites de precio que informa MeLi."""
    try:
        lst = promos.item_promotions(client, item_id)
    except MeliError as e:
        return {"nota": f"No se pudo consultar: {e}"[:150]}

    def pick(p):
        return {
            "max_permitido": to_number(p.get("max_discounted_price")),
            "min_permitido": to_number(p.get("min_discounted_price")),
            "sugerido_meli": to_number(p.get("suggested_discounted_price")),
        }

    exact = [p for p in lst if (promo_id and p.get("id") == promo_id) or (not promo_id and p.get("type") == ptype)]
    for p in exact + [p for p in lst if p not in exact]:
        lim = pick(p)
        if any(v for v in lim.values()):
            lim["nota"] = "" if p in exact else f"límite tomado de {p.get('type')}"
            return lim
    return {"nota": "MeLi no informa un máximo para esta publicación (puede ser muy nueva o con precio reciente)."}


def _with_limits(client, df, promo_id, ptype):
    rows = df.to_dict("records")
    with ThreadPoolExecutor(max_workers=4) as ex:
        lims = list(ex.map(lambda r: price_limits(client, r["item_id"], promo_id, ptype), rows))
    out = df.copy()
    for col in ("max_permitido", "min_permitido", "sugerido_meli", "nota"):
        out[col] = [l.get(col) for l in lims]
    return out


def save_run(key: str, res: pd.DataFrame, client: MeliClient, ptype: str, promo_id: str | None,
             start=None, finish=None) -> None:
    """Guardar el resultado de la corrida (y enriquecer los rechazos por credibilidad)."""
    bad = res["error"].map(is_cred)
    if bad.any():
        with st.spinner(f"Consultando a MeLi el precio permitido de {int(bad.sum())} publicaciones rechazadas…"):
            enriched = _with_limits(client, res[bad], promo_id, ptype)
        res = res.copy()
        for col in ("max_permitido", "min_permitido", "sugerido_meli", "nota"):
            res.loc[bad, col] = enriched[col].values
    st.session_state[f"last_{key}"] = {"res": res, "ptype": ptype, "promo_id": promo_id,
                                       "start": start, "finish": finish}


def render_last(client: MeliClient, key: str, filename: str, cols: list[str]) -> None:
    last = st.session_state.get(f"last_{key}")
    if not last:
        return
    res = last["res"]
    ok = (res["resultado"] == "OK").sum()
    err = (res["resultado"] == "ERROR").sum()
    st.divider()
    st.subheader("Resultado")
    (st.success if not err else st.warning)(f"{ok} OK · {err} con error")
    show = [c for c in cols + ["resultado", "max_permitido", "min_permitido", "sugerido_meli", "nota", "error",
                               "procesado"] if c in res]
    st.dataframe(res[show], width="stretch", hide_index=True)
    st.download_button("⬇️ Descargar resultado", to_xlsx(res[show]), file_name=filename, key=f"dl_last_{key}")

    cred = res[(res["resultado"] == "ERROR") & res["error"].map(is_cred)]
    if not cred.empty:
        st.markdown("#### ⚠️ Rechazados por *precio no creíble*")
        st.caption("MeLi compara contra el historial de precios de cada publicación (precios más bajos recientes, "
                   "subas de precio recientes o publicaciones nuevas sin historial). "
                   "**max_permitido** es el precio promo más alto que MeLi acepta hoy para esa publicación.")
        retry = cred[cred.get("max_permitido").notna()] if "max_permitido" in cred else cred.iloc[0:0]
        if retry.empty:
            st.info("MeLi no devolvió un precio máximo para estas publicaciones. Probá con un descuento mayor "
                    "o esperá unos días si el precio de lista se cambió hace poco.")
        else:
            prev = retry[[c for c in ["clave", "item_id", "titulo", "precio_lista", "precio_nuevo", "max_permitido"]
                          if c in retry]].copy()
            if "precio_lista" in prev:
                prev["dto_%_nuevo"] = (1 - prev["max_permitido"] / prev["precio_lista"]).mul(100).round(1)
            st.dataframe(prev, width="stretch", hide_index=True)
            ok2 = st.checkbox(f"Confirmo reintentar {len(retry)} publicaciones con el precio máximo permitido",
                              key=f"cred_ok_{key}")
            if st.button(f"🔁 Reintentar {len(retry)} con el máximo permitido", disabled=not ok2,
                         key=f"cred_btn_{key}"):
                ptype, pid, s, f = last["ptype"], last["promo_id"], last["start"], last["finish"]

                def job(r):
                    if ptype == "PRICE_DISCOUNT":
                        promos.add_item(client, r["item_id"], ptype, deal_price=r["max_permitido"], start=s, finish=f)
                    else:
                        promos.add_item(client, r["item_id"], ptype, pid, deal_price=r["max_permitido"])

                rr = run_bulk(retry.to_dict("records"), job, label="Reintentando")
                rr["precio_nuevo"] = rr["max_permitido"]
                base = res.set_index("item_id")
                upd = rr.set_index("item_id")[["precio_nuevo", "resultado", "error", "procesado"]]
                base.update(upd)
                save_run(key, base.reset_index(), client, ptype, pid, s, f)
                st.rerun()

    if st.button("Cerrar resultado", key=f"close_{key}"):
        st.session_state.pop(f"last_{key}", None)
        st.rerun()
