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
    import base64
    from pathlib import Path
    ic = Path(__file__).resolve().parent.parent / "assets" / "icon.svg"
    img = f'<img src="data:image/svg+xml;base64,{base64.b64encode(ic.read_bytes()).decode()}"/>' if ic.exists() else ""
    st.markdown(f'<div class="mo-login">{img}<div class="mo-title" style="font-size:2.2rem">MeLi Ops</div>'
                '<div class="mo-sub" style="margin:0 auto 18px">Centro de control de tus tiendas oficiales · Distrinando</div>'
                '</div>', unsafe_allow_html=True)
    _, mid, _ = st.columns([1, 1.2, 1])
    typed = mid.text_input("Contraseña", type="password", placeholder="••••••••")
    if typed:
        if hmac.compare_digest(typed, str(pwd)):
            st.session_state["auth_ok"] = True
            st.rerun()
        mid.error("Contraseña incorrecta")
    st.stop()


def pick_account() -> MeliClient:
    tm = get_token_manager()
    accounts = tm.accounts()
    if not accounts:
        st.warning("No hay cuentas conectadas. Andá a **Cuentas** y conectá al menos una.")
        st.stop()
    from .selector_marca import elegir_cuenta
    return MeliClient(tm, elegir_cuenta(accounts))


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

