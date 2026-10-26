from pathlib import Path

import streamlit as st

from meli.auth import AuthError, get_token_manager
from meli.config import require_secrets
from meli.theme import apply_theme
from meli.shopify_auth import handle_callback as shopify_callback
from meli.ui import require_login

ASSETS = Path(__file__).parent / "assets"
st.set_page_config(page_title="MeLi Ops · Distrinando", page_icon=str(ASSETS / "icon.svg"), layout="wide")
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

pg = st.navigation(
    {
        "": [
            st.Page("views/inicio.py", title="Inicio", icon=":material/space_dashboard:", default=True),
        ],
        "Promociones": [
            st.Page("views/campanas.py", title="Campañas", icon=":material/campaign:"),
            st.Page("views/cargar_promo.py", title="Cargar a campaña", icon=":material/sell:"),
            st.Page("views/descuentos.py", title="Descuentos", icon=":material/percent:"),
            st.Page("views/invitaciones.py", title="Invitaciones MeLi", icon=":material/mark_email_unread:"),
        ],
        "Precios": [
            st.Page("views/omnicanal.py", title="Precios omnicanal", icon=":material/sync_alt:"),
            st.Page("views/analisis_precios.py", title="Análisis de precios", icon=":material/insights:"),
            st.Page("views/precios.py", title="Precios masivos MeLi", icon=":material/price_change:"),
            st.Page("views/inconsistencias.py", title="Precios distintos", icon=":material/balance:"),
        ],
        "Catálogo y marca": [
            st.Page("views/contenido.py", title="Contenido SEO", icon=":material/auto_awesome:"),
            st.Page("views/clips.py", title="Clips", icon=":material/movie:"),
            st.Page("views/proteccion.py", title="Protección de marca", icon=":material/shield:"),
        ],
        "Shopify": [
            st.Page("views/shop_catalogo.py", title="Catálogo Shopify", icon=":material/inventory_2:"),
            st.Page("views/shop_seo.py", title="SEO y calidad", icon=":material/travel_explore:"),
        ],
        "Configuración": [
            st.Page("views/historial.py", title="Historial", icon=":material/history:"),
            st.Page("views/cuentas.py", title="Cuentas", icon=":material/key:"),
        ],
    },
    expanded=True,
)
if _msg := st.session_state.pop("flash", None):
    (st.success if _msg.startswith("✅") else st.error)(_msg)
pg.run()
