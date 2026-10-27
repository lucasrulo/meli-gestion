import time
from datetime import datetime

import streamlit as st

from meli.auth import get_token_manager
from meli.config import secret
from meli import shopify as sh
from meli.theme import card, hero

hora = datetime.now().hour
saludo = "Buen día" if hora < 13 else "Buenas tardes" if hora < 20 else "Buenas noches"
hero(f"{saludo}, equipo Distrinando", "Centro de control de las tiendas oficiales en MercadoLibre y Shopify: precios, promociones, "
     "contenido y protección de marca, en masivo y con vista previa.", "MELI OPS · ONLINE")

accounts = get_token_manager().accounts()
vigentes = sum(1 for a in accounts.values() if a.get("expires_at", 0) > time.time())
m = st.columns(4)
m[0].metric("Cuentas conectadas", len(accounts))
m[1].metric("Tokens activos", f"{vigentes}/{len(accounts)}" if accounts else "—")
m[2].metric("IA · Claude", "ON" if secret("ANTHROPIC_API_KEY") else "OFF",
            help=None if secret("ANTHROPIC_API_KEY") else "Cargá ANTHROPIC_API_KEY en Secrets para activarla.")
m[3].metric("Tiendas Shopify", len(sh.stores()))

if accounts:
    st.caption("Tiendas: " + " · ".join(f"`{a.get('alias') or a.get('nickname')}`" for a in accounts.values()))
else:
    st.warning("Todavía no hay cuentas conectadas. Empezá por **Cuentas**.")

from meli.menu import MENU  # noqa: E402

for seccion, mods in MENU.items():
    st.markdown(f"### {seccion}")
    cols = st.columns(4)
    for i, (page, tit, _ic, emoji, txt, badge) in enumerate(mods):
        with cols[i % 4]:
            card(emoji, tit, txt, badge)
            st.page_link(page, label=f"Abrir {tit} →")
