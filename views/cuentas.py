import time
from datetime import datetime

import pandas as pd
import streamlit as st

from meli.auth import get_token_manager

st.title("🔑 Cuentas MercadoLibre")

if msg := st.session_state.pop("flash", None):
    (st.success if msg.startswith("✅") else st.error)(msg)

tm = get_token_manager()

c1, c2 = st.columns([1, 1])
c1.link_button("➕ Conectar cuenta", tm.auth_url(), type="primary",
               help="Antes, iniciá sesión en mercadolibre.com.ar con la cuenta de la tienda a conectar.")
if c2.button("🔄 Recargar"):
    tm.accounts(reload=True)
    st.rerun()

st.caption("Para conectar otra tienda: cerrá sesión en MeLi, entrá con la cuenta de esa tienda y tocá **Conectar cuenta**. "
           "El link vale 15 minutos.")

accounts = tm.accounts()
if not accounts:
    st.info("Todavía no hay cuentas conectadas.")
    st.stop()

rows = []
now = time.time()
for uid, a in accounts.items():
    rows.append({
        "alias": a.get("alias"),
        "nickname": a.get("nickname"),
        "user_id": uid,
        "token": "vigente" if a.get("expires_at", 0) > now else "se renueva al usar",
        "conectada": a.get("connected_at"),
    })
st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

st.subheader("Editar")
uid = st.selectbox("Cuenta", list(accounts), format_func=lambda k: accounts[k].get("alias") or k)
c1, c2, c3 = st.columns([2, 1, 1])
alias = c1.text_input("Alias (ej: Columbia)", value=accounts[uid].get("alias") or "")
if c2.button("Guardar alias", width="stretch"):
    tm.set_alias(uid, alias.strip())
    st.rerun()
if c3.button("Probar conexión", width="stretch"):
    try:
        tok = tm.get_access_token(uid)
        import requests
        me = requests.get("https://api.mercadolibre.com/users/me",
                          headers={"Authorization": f"Bearer {tok}"}, timeout=20).json()
        st.success(f"OK · {me.get('nickname')} · {datetime.now():%H:%M:%S}")
    except Exception as e:  # noqa: BLE001
        st.error(str(e))

with st.expander("Desconectar cuenta"):
    if st.checkbox(f"Confirmo desconectar {accounts[uid].get('alias')}"):
        if st.button("Desconectar", type="secondary"):
            tm.remove(uid)
            st.rerun()
