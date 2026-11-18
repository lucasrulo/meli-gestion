import time
from datetime import datetime

import streamlit as st

from meli import shopify as sh
from meli.auth import get_token_manager
from meli.config import secret
from meli.menu import MENU
from meli.theme import card, hero

hora = datetime.now().hour
saludo = "Buen día" if hora < 13 else "Buenas tardes" if hora < 20 else "Buenas noches"
hero(f"{saludo}, equipo Distrinando", "MercadoLibre y Shopify en un solo lugar: cada canal con sus herramientas, y una "
     "sección para trabajar los dos juntos.", "OMNIOPS · ONLINE")

accounts = get_token_manager().accounts()
vigentes = sum(1 for a in accounts.values() if a.get("expires_at", 0) > time.time())
tiendas = sh.stores()
m = st.columns(4)
m[0].metric("🟡 Cuentas MeLi", len(accounts), help=" · ".join(a.get("alias") or a.get("nickname") or "" for a in accounts.values()))
m[1].metric("Tokens MeLi activos", f"{vigentes}/{len(accounts)}" if accounts else "—")
m[2].metric("🟢 Tiendas Shopify", len(tiendas), help=" · ".join(v["nombre"] for v in tiendas.values()))
m[3].metric("✨ IA · Claude", "ON" if secret("ANTHROPIC_API_KEY") else "OFF",
            help=None if secret("ANTHROPIC_API_KEY") else "Cargá ANTHROPIC_API_KEY en Secrets para activarla.")
if not accounts or not tiendas:
    st.warning("Falta conectar " + " y ".join(x for x, ok in (("cuentas de MeLi", accounts), ("tiendas de Shopify", tiendas))
                                               if not ok) + ". Andá a **Configuración → Cuentas y tiendas**.")

ICONO = {"MercadoLibre": "🟡", "Shopify": "🟢", "MeLi ↔ Shopify": "🔀", "Configuración": "⚙️"}
DESC = {"MercadoLibre": "Todo lo que se hace solo en MercadoLibre.",
        "Shopify": "Todo lo que se hace solo en las tiendas Shopify.",
        "MeLi ↔ Shopify": "Cruzar los dos canales: comparar, igualar precios y copiar contenido.",
        "Configuración": "Conexiones e historial de cambios."}
for seccion, mods in MENU.items():
    st.markdown(f"### {ICONO.get(seccion, '')} {seccion}")
    st.caption(DESC.get(seccion, ""))
    cols = st.columns(4)
    for i, (page, tit, _ic, emoji, txt, badge) in enumerate(mods):
        with cols[i % 4]:
            card(emoji, tit, txt, badge)
            st.page_link(page, label=f"Abrir {tit} →")
