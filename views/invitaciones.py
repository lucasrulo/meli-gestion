from datetime import datetime

import pandas as pd
import streamlit as st

from meli import promos
from meli.api import MeliError
from meli.bulk import run_bulk
from meli.excel import read_excel, to_number
from meli.ui import catalog_index, pick_account, show_results

st.session_state["_page"] = "invit"
st.title("📨 Invitaciones de MeLi")
st.caption("Campañas de MercadoLibre donde tus publicaciones son *candidatas*. Elegís cuáles sumar y a qué precio.")
client = pick_account()

key = f"promos_{client.user_id}"
if st.button("🔄 Actualizar promociones") or key not in st.session_state:
    try:
        with st.spinner("Leyendo promociones…"):
            st.session_state[key] = promos.list_promotions(client)
    except MeliError as e:
        st.error(str(e))
        st.stop()

meli_promos = [p for p in st.session_state[key]
               if p.get("type") not in {"SELLER_CAMPAIGN", "PRICE_DISCOUNT", "SELLER_COUPON_CAMPAIGN"}
               and p.get("status") in {"started", "pending", None}]
if not meli_promos:
    st.info("No hay campañas de MeLi vigentes o próximas para esta cuenta.")
    st.stop()

i = st.selectbox(
    "Campaña",
    range(len(meli_promos)),
    format_func=lambda k: f"{meli_promos[k].get('name') or meli_promos[k]['id']} · "
                          f"{promos.TYPE_LABELS.get(meli_promos[k]['type'], meli_promos[k]['type'])} · "
                          f"{meli_promos[k].get('status')} · {str(meli_promos[k].get('start_date', ''))[:10]} → "
                          f"{str(meli_promos[k].get('finish_date', ''))[:10]}",
)
p = meli_promos[i]
ptype = p["type"]
with st.expander("Detalle de la campaña"):
    st.json(p)

ck = f"cands_{client.user_id}_{p['id']}"
if st.button("📥 Traer candidatos", type="primary") or ck in st.session_state:
    if ck not in st.session_state:
        try:
            with st.spinner("Leyendo candidatos…"):
                st.session_state[ck] = promos.promotion_items(client, p["id"], ptype, status="candidate")
        except MeliError as e:
            st.error(str(e))
            st.stop()
else:
    st.stop()

cands = pd.DataFrame(st.session_state[ck])
if cands.empty:
    st.info("No hay items candidatos en esta campaña.")
    st.stop()

index = catalog_index(client)
info = (index.groupby("item_id")
        .agg(titulo=("titulo", "first"), skus=("sku", lambda s: ", ".join(sorted({x for x in s if x}))[:120]),
             stock=("stock", "first"))
        .reset_index())
df = cands.rename(columns={"id": "item_id"}).merge(info, on="item_id", how="left")

# ---------- Filtros ----------
f1, f2, f3 = st.columns(3)
sku_file = f1.file_uploader("Filtrar por Excel de SKUs (opcional)", type=["xlsx", "xls", "csv"])
if sku_file:
    sk = read_excel(sku_file)
    col = "sku" if "sku" in sk else sk.columns[0]
    wanted = set(sk[col].dropna().astype(str).str.strip().str.upper())
    df = df[df["skus"].fillna("").str.upper().apply(lambda s: any(w in s.split(", ") for w in wanted))
            | df["item_id"].isin(wanted)]
if "seller_percentage" in df:
    mx = f2.number_input("Máx. % que aporto yo", 0.0, 100.0, 100.0, step=1.0)
    df = df[df["seller_percentage"].fillna(0).astype(float) <= mx]
sel_all = f3.checkbox("Marcar todos", value=False)

needs_price = ptype in promos.PRICE_TYPES
if needs_price:
    sug = df.get("suggested_discounted_price")
    df["deal_price"] = sug if sug is not None else df.get("price")
df.insert(0, "sumar", sel_all)

cols = ["sumar", "item_id", "titulo", "skus", "stock", "original_price", "price", "deal_price",
        "suggested_discounted_price", "min_discounted_price", "max_discounted_price",
        "meli_percentage", "seller_percentage", "offer_id"]
cols = [c for c in cols if c in df]
if ptype == "LIGHTNING":
    df["stock_oferta"] = None
    cols.append("stock_oferta")

st.write(f"**{len(df)} candidatos**" + (" · editá *deal_price* si querés otro precio" if needs_price else ""))
editable = {"sumar", "deal_price", "stock_oferta"}
ed = st.data_editor(df[cols], width="stretch", hide_index=True, key=f"ed_{ck}",
                    disabled=[c for c in cols if c not in editable])

todo = ed[ed["sumar"]].to_dict("records")
st.write(f"Seleccionados: **{len(todo)}**")
if not todo:
    st.stop()

if needs_price:
    bad = [r["item_id"] for r in todo if to_number(r.get("deal_price")) is None]
    if bad:
        st.error(f"Faltan precios en: {', '.join(bad[:10])}")
        st.stop()

ok = st.checkbox(f"Confirmo sumar {len(todo)} publicaciones a «{p.get('name')}»")
if st.button(f"✅ Sumar {len(todo)}", type="primary", disabled=not ok):
    def job(r):
        promos.add_item(
            client, r["item_id"], ptype, p["id"],
            deal_price=to_number(r.get("deal_price")) if needs_price else None,
            offer_id=r.get("offer_id") if isinstance(r.get("offer_id"), str) else None,
            stock=to_number(r.get("stock_oferta")),
        )

    res = run_bulk(todo, job, label="Sumando")
    st.session_state.pop(ck, None)
    show_results(res, f"invitacion_{p['id']}_{datetime.now():%Y%m%d_%H%M}.xlsx")
