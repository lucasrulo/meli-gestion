from datetime import datetime

import pandas as pd
import streamlit as st

from meli import ads
from meli import historial
from meli.api import MeliError
from meli.auth import get_token_manager
from meli.bulk import run_bulk
from meli.excel import to_xlsx
from meli.theme import hero
from meli.ui import pick_account, show_results

hero("Publicidad MeLi", "Campañas de Product Ads: presupuesto, estrategia, ROAS objetivo y ajuste automático de presupuesto, "
     "en masa y con métricas.", "MELI · ADS")
client = pick_account()
alias = get_token_manager().accounts().get(client.user_id, {}).get("alias") or client.user_id

try:
    adv = ads.anunciante(client)
except MeliError as e:
    st.error(f"No pude leer el anunciante de Product Ads: {e}")
    st.stop()
if not adv:
    st.info("Esta cuenta no tiene Product Ads activo (o la app no tiene permiso de Publicidad).")
    st.stop()
site, adv_id = adv.get("site_id", "MLA"), adv["advertiser_id"]

c1, c2 = st.columns([1, 3], vertical_alignment="bottom")
dias = c1.selectbox("Métricas de los últimos", [7, 15, 30, 60, 90], index=2, format_func=lambda d: f"{d} días",
                    key="ads_dias")
k, kw, kv = f"ads_{client.user_id}_{dias}", f"ads_ws_{client.user_id}", f"ads_v_{client.user_id}"
if c2.button("🔄 Releer campañas", key="ads_ref") or k not in st.session_state:
    with st.spinner("Leyendo campañas y métricas…"):
        try:
            st.session_state[k] = ads.campanas(client, site, adv_id, dias)
        except MeliError as e:
            st.error(str(e))
            st.stop()
    st.session_state.pop(kw, None)
C = st.session_state[k]
if C.empty:
    st.info("No hay campañas de Product Ads en esta cuenta.")
    st.stop()

# ---- resumen
inv, ven = C["inversion"].fillna(0).sum(), C["ventas_$"].fillna(0).sum()
m = st.columns(5)
m[0].metric("Campañas", len(C), f"{int((C['estado'] == 'active').sum())} activas", delta_color="off")
m[1].metric("Presupuesto diario total", f"$ {C.loc[C['estado'] == 'active', 'presupuesto'].fillna(0).sum():,.0f}".replace(",", "."))
m[2].metric(f"Inversión {dias} días", f"$ {inv:,.0f}".replace(",", "."))
m[3].metric("ROAS real", f"{ven / inv:.1f}x" if inv else "—", help="Ventas atribuidas / inversión.")
m[4].metric("Con ajuste automático", int((C["ajuste_auto"] == True).sum()))  # noqa: E712

# ---- copia de trabajo editable
if kw not in st.session_state:
    st.session_state[kw] = C[["id", "nombre", "estado", "presupuesto", "estrategia", "roas_objetivo", "ajuste_auto"]].copy()
    st.session_state[kv] = 0
W = st.session_state[kw]

st.markdown("#### Cambios masivos")
st.caption("Tildá campañas en la tabla y aplicá una acción, o editá las celdas directamente. Nada se envía a MeLi hasta "
           "**Aplicar cambios**.")
a1, a2, a3, a4 = st.columns([1.1, 1.3, 1, 1], vertical_alignment="bottom")
acc = a1.selectbox("Acción", ["Ajuste automático: activar", "Ajuste automático: desactivar", "Presupuesto: subir/bajar %",
                              "Presupuesto: fijar monto", "ROAS objetivo: fijar", "Estado: activar", "Estado: pausar"],
                   key="ads_acc")
val = None
if acc.startswith("Presupuesto: subir"):
    val = a2.number_input("% (negativo baja)", -90, 500, 10, 5, key="ads_pct")
elif acc.startswith("Presupuesto: fijar"):
    val = a2.number_input("Presupuesto diario $", 0, 100_000_000, 20_000, 1_000, key="ads_monto")
elif acc.startswith("ROAS"):
    val = a2.number_input("ROAS objetivo (1x a 35x)", 1.0, 35.0, 8.0, 0.5, key="ads_roas")
alcance = a3.radio("A", ["Tildadas", "Todas"], horizontal=True, key="ads_alc")

view = W.merge(C[["id", "inversion", "ventas_$", "roas", "acos", "unidades", "clics"]], on="id", how="left")
view.insert(0, "✔", False)
ed = st.data_editor(
    view, hide_index=True, width="stretch", key=f"ads_ed_{st.session_state[kv]}",
    height=min(40 + 36 * len(view), 520),
    disabled=["id", "nombre", "inversion", "ventas_$", "roas", "acos", "unidades", "clics"],
    column_order=["✔", "nombre", "estado", "presupuesto", "ajuste_auto", "estrategia", "roas_objetivo",
                  "inversion", "ventas_$", "roas", "acos", "unidades", "clics"],
    column_config={
        "✔": st.column_config.CheckboxColumn(width="small"),
        "nombre": st.column_config.TextColumn("Campaña", width="medium"),
        "estado": st.column_config.SelectboxColumn("Estado", options=["active", "paused"]),
        "presupuesto": st.column_config.NumberColumn("✏️ Presupuesto $", format="$ %d", min_value=0),
        "ajuste_auto": st.column_config.CheckboxColumn("✏️ Ajuste auto"),
        "estrategia": st.column_config.SelectboxColumn("✏️ Estrategia", options=list(ads.ESTRATEGIAS)),
        "roas_objetivo": st.column_config.NumberColumn("✏️ ROAS obj.", min_value=1.0, max_value=35.0, format="%.1fx"),
        "inversion": st.column_config.NumberColumn(f"Inversión {dias}d", format="$ %d"),
        "ventas_$": st.column_config.NumberColumn("Ventas $", format="$ %d"),
        "roas": st.column_config.NumberColumn("ROAS", format="%.1fx"),
        "acos": st.column_config.NumberColumn("ACOS %", format="%.1f"),
    })
# guardar ediciones manuales en la copia de trabajo
editable = ["estado", "presupuesto", "ajuste_auto", "estrategia", "roas_objetivo"]
st.session_state[kw] = ed[["id", "nombre"] + editable].copy()
W = st.session_state[kw]

if a4.button("Aplicar a la tabla", key="ads_do", width="stretch"):
    ids = ed.loc[ed["✔"], "id"].tolist() if alcance == "Tildadas" else W["id"].tolist()
    if not ids:
        st.warning("Tildá al menos una campaña.")
    else:
        msk = W["id"].isin(ids)
        if acc.endswith("activar") and acc.startswith("Ajuste"):
            W.loc[msk, "ajuste_auto"] = True
        elif acc.endswith("desactivar"):
            W.loc[msk, "ajuste_auto"] = False
        elif acc.startswith("Presupuesto: subir"):
            W.loc[msk, "presupuesto"] = (W.loc[msk, "presupuesto"].fillna(0) * (1 + val / 100)).round(0)
        elif acc.startswith("Presupuesto: fijar"):
            W.loc[msk, "presupuesto"] = float(val)
        elif acc.startswith("ROAS"):
            W.loc[msk, "roas_objetivo"] = float(val)
        elif acc == "Estado: activar":
            W.loc[msk, "estado"] = "active"
        elif acc == "Estado: pausar":
            W.loc[msk, "estado"] = "paused"
        st.session_state[kw] = W
        st.session_state[kv] += 1
        st.rerun()

# ---- diferencias
orig = C.set_index("id")
cambios = []
for _, r in W.iterrows():
    o = orig.loc[r["id"]]
    d, a = {}, {}
    for campo, api in (("estado", "status"), ("presupuesto", "budget"), ("ajuste_auto", "automatic_budget"),
                       ("estrategia", "strategy"), ("roas_objetivo", "roas_target")):
        nv, ov = r[campo], o[campo]
        if pd.isna(nv) and pd.isna(ov):
            continue
        if campo in ("presupuesto", "roas_objetivo"):
            if pd.notna(nv) and (pd.isna(ov) or abs(float(nv) - float(ov)) > 0.001):
                d[api], a[api] = float(nv), (None if pd.isna(ov) else float(ov))
        elif nv != ov and not (pd.isna(nv)):
            d[api] = nv.lower() if campo == "estrategia" else (bool(nv) if campo == "ajuste_auto" else nv)
            a[api] = (ov.lower() if isinstance(ov, str) and campo == "estrategia" else ov)
    if d:
        cambios.append({"id": r["id"], "nombre": r["nombre"], "despues": d, "antes": a})

st.markdown("#### Aplicar")
if not cambios:
    st.caption("Sin cambios pendientes.")
else:
    pres_a = sum(c["antes"].get("budget") or 0 for c in cambios if "budget" in c["despues"])
    pres_d = sum(c["despues"].get("budget") or 0 for c in cambios if "budget" in c["despues"])
    st.dataframe(pd.DataFrame([{"Campaña": c["nombre"],
                                "Cambios": " · ".join(f"{k_}: {c['antes'].get(k_)} → {v_}" for k_, v_ in c["despues"].items())}
                               for c in cambios]), hide_index=True, width="stretch")
    if pres_d != pres_a:
        st.info(f"Presupuesto diario de las campañas modificadas: **$ {pres_a:,.0f} → $ {pres_d:,.0f}** "
                f"({pres_d - pres_a:+,.0f} por día)".replace(",", "."))
    if any("automatic_budget" in c["despues"] for c in cambios):
        st.caption("🧪 El ajuste automático por API es **experimental**: después de aplicarlo la app relee cada campaña "
                   "y te dice si MeLi lo tomó.")
    b1, b2, b3 = st.columns([2, 1, 1], vertical_alignment="center")
    ok = b1.checkbox(f"Confirmo aplicar {len(cambios)} cambio(s) en Publicidad (afecta la inversión)", key=f"ads_ok_{len(cambios)}")
    if b3.button("Descartar", key="ads_desc", width="stretch"):
        st.session_state.pop(kw, None)
        st.rerun()
    if b2.button("💸 Aplicar cambios", type="primary", disabled=not ok, key="ads_go", width="stretch"):
        log = []

        def job(c):
            ads.modificar(client, site, c["id"], c["despues"])
            nota = ""
            if "automatic_budget" in c["despues"]:
                real = ads.detalle(client, site, c["id"]).get("automatic_budget")
                if real is not None and bool(real) != bool(c["despues"]["automatic_budget"]):
                    nota = "MeLi no aplicó el ajuste automático (hacelo desde el panel)"
            log.append({"id": c["id"], "label": c["campaña"], "antes": c["antes"], "despues": c["despues"],
                        "ok": True, "error": nota})
            if nota:
                raise RuntimeError(nota)

        res = run_bulk([{"id": c["id"], "campaña": c["nombre"], "despues": c["despues"], "antes": c["antes"]}
                        for c in cambios], job, label="Aplicando en Publicidad")
        historial.registrar("MeLi", alias, "meli_ads", f"{alias}: Publicidad, {len(log)} campaña(s)", log,
                            {"user_id": client.user_id, "site": site})
        show_results(res.assign(cambios=res["despues"].astype(str)).drop(columns=["despues", "antes"]),
                     f"publicidad_{datetime.now():%Y%m%d_%H%M}.xlsx")
        st.session_state.pop(k, None)
        st.session_state.pop(kw, None)

st.divider()
st.caption("**Ajuste de presupuesto para fechas especiales**: MeLi no lo expone por API; se activa desde el panel de "
           "Publicidad de cada campaña.")
st.download_button("⬇️ Descargar campañas y métricas (Excel)", to_xlsx(C), f"publicidad_{alias}_{dias}d.xlsx")
