"""Helpers de interfaz compartidos entre páginas."""
import hmac
import time

import pandas as pd
import streamlit as st

from .api import MeliClient
from .auth import get_token_manager
from .catalog import load_index
from .config import secret


def require_login() -> None:
    pwd = secret("APP_PASSWORD")
    if not pwd or st.session_state.get("auth_ok"):
        return
    st.title("🔒 Gestión MercadoLibre")
    typed = st.text_input("Contraseña", type="password")
    if typed:
        if hmac.compare_digest(typed, str(pwd)):
            st.session_state["auth_ok"] = True
            st.rerun()
        st.error("Contraseña incorrecta")
    st.stop()


def pick_account() -> MeliClient:
    tm = get_token_manager()
    accounts = tm.accounts()
    if not accounts:
        st.warning("No hay cuentas conectadas. Andá a **Cuentas** y conectá al menos una.")
        st.stop()
    ids = sorted(accounts, key=lambda k: (accounts[k].get("alias") or "").lower())
    uid = st.sidebar.selectbox(
        "Cuenta MeLi",
        ids,
        format_func=lambda k: accounts[k].get("alias") or accounts[k].get("nickname") or k,
        key="account_uid",
    )
    return MeliClient(tm, uid)


INDEX_VERSION = 2  # subir cuando cambian las columnas del índice → invalida el caché viejo


@st.cache_data(ttl=3600, show_spinner=False)
def _cached_index(user_id: str, nonce: int, version: int = INDEX_VERSION) -> pd.DataFrame:
    return load_index(MeliClient(get_token_manager(), user_id))


def index_for(user_id: str) -> pd.DataFrame:
    """Índice de cualquier cuenta conectada (mismo caché que catalog_index)."""
    return _cached_index(str(user_id), st.session_state.get(f"catalog_nonce_{user_id}", 0))


def catalog_index(client: MeliClient) -> pd.DataFrame:
    """Índice SKU→item cacheado 1 h por cuenta, con botón para refrescar."""
    key = f"catalog_nonce_{client.user_id}"
    st.session_state.setdefault(key, 0)
    c1, c2 = st.columns([3, 1])
    if c2.button("🔄 Refrescar catálogo", key=f"refresh_{client.user_id}_{st.session_state.get('_page', '')}"):
        st.session_state[key] = int(time.time())
    with st.spinner("Leyendo publicaciones de la cuenta (la primera vez tarda un poco)…"):
        idx = _cached_index(client.user_id, st.session_state[key])
    c1.caption(f"Catálogo: {idx['item_id'].nunique()} publicaciones activas/pausadas · "
               f"{idx['sku'].notna().sum()} SKUs")
    return idx


def show_results(df: pd.DataFrame, filename: str) -> None:
    from .excel import to_xlsx
    ok = (df["resultado"] == "OK").sum()
    err = (df["resultado"] == "ERROR").sum()
    (st.success if not err else st.warning)(f"Listo: {ok} OK · {err} con error")
    st.dataframe(df, width="stretch", hide_index=True)
    st.download_button("⬇️ Descargar resultado", to_xlsx(df), file_name=filename,
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

