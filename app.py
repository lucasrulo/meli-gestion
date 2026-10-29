from pathlib import Path

import streamlit as st

from meli.auth import AuthError, get_token_manager
from meli.config import require_secrets
from meli.theme import apply_theme
from meli.shopify_auth import handle_callback as shopify_callback
from meli.ui import require_login

ASSETS = Path(__file__).parent / "assets"
st.set_page_config(page_title="OmniOps · Distrinando", page_icon=str(ASSETS / "icon.svg"), layout="wide")
apply_theme()
st.logo(str(ASSETS / "logo.svg"), size="large", icon_image=str(ASSETS / "icon.svg"))

require_secrets("MELI_APP_ID", "MELI_CLIENT_SECRET", "MELI_REDIRECT_URI", "GITHUB_TOKEN", "GITHUB_REPO")
require_login()
shopify_callback()  # vuelta de Shopify (?shop=...&hmac=...) — antes que el callback de MeLi

# ---- Callback OAuth: MeLi vuelve a la URL raíz con ?code=...&state=... ----
qp = st.query_params
if "code" in qp:
    tm = get_token_manager()
    code, state = qp.get("code"), qp.get("state", "")
    st.query_params.clear()
    if not tm.valid_state(state):
        st.error("El link de conexión venció o no es válido. Generá uno nuevo desde Cuentas.")
    else:
        try:
            rec = tm.exchange_code(code)
            st.session_state["flash"] = f"✅ Cuenta conectada: {rec['nickname']} ({rec['user_id']})"
        except AuthError as e:
            st.session_state["flash"] = f"❌ {e}"
        st.rerun()

from meli.menu import MENU  # noqa: E402

nav = {"": [st.Page("views/inicio.py", title="Inicio", icon=":material/space_dashboard:", default=True)]}
for seccion, paginas in MENU.items():
    nav[seccion] = [st.Page(f, title=t, icon=f":material/{ic}:") for f, t, ic, *_ in paginas]
pg = st.navigation(nav, expanded=True)
if _msg := st.session_state.pop("flash", None):
    (st.success if _msg.startswith("✅") else st.error)(_msg)
pg.run()
