import streamlit as st

from meli.auth import AuthError, get_token_manager
from meli.config import require_secrets
from meli.ui import require_login

st.set_page_config(page_title="Gestión MeLi · Distrinando", page_icon="🛒", layout="wide")

require_secrets("MELI_APP_ID", "MELI_CLIENT_SECRET", "MELI_REDIRECT_URI", "GITHUB_TOKEN", "GITHUB_REPO")
require_login()

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

pg = st.navigation(
    [
        st.Page("views/cuentas.py", title="Cuentas", icon="🔑", default=True),
        st.Page("views/campanas.py", title="Campañas", icon="📣"),
        st.Page("views/cargar_promo.py", title="Cargar a campaña", icon="🏷️"),
        st.Page("views/descuentos.py", title="Descuentos", icon="🔖"),
        st.Page("views/invitaciones.py", title="Invitaciones MeLi", icon="📨"),
        st.Page("views/precios.py", title="Precios masivos", icon="💲"),
        st.Page("views/inconsistencias.py", title="Precios distintos", icon="⚖️"),
        st.Page("views/proteccion.py", title="Protección de marca", icon="🛡️"),
    ]
)
pg.run()
