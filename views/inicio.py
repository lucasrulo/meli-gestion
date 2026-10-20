import time
from datetime import datetime

import streamlit as st

from meli.auth import get_token_manager
from meli.config import secret
from meli.theme import card, hero

hora = datetime.now().hour
saludo = "Buen día" if hora < 13 else "Buenas tardes" if hora < 20 else "Buenas noches"
hero(f"{saludo}, equipo Distrinando", "Centro de control de las tiendas oficiales en MercadoLibre: precios, promociones, "
     "contenido y protección de marca, en masivo y con vista previa.", "MELI OPS · ONLINE")

accounts = get_token_manager().accounts()
vigentes = sum(1 for a in accounts.values() if a.get("expires_at", 0) > time.time())
m = st.columns(4)
m[0].metric("Cuentas conectadas", len(accounts))
m[1].metric("Tokens activos", f"{vigentes}/{len(accounts)}" if accounts else "—")
m[2].metric("IA · Claude", "ON" if secret("ANTHROPIC_API_KEY") else "OFF",
            help=None if secret("ANTHROPIC_API_KEY") else "Cargá ANTHROPIC_API_KEY en Secrets para activarla.")
m[3].metric("Módulos", 9)

if accounts:
    st.caption("Tiendas: " + " · ".join(f"`{a.get('alias') or a.get('nickname')}`" for a in accounts.values()))
else:
    st.warning("Todavía no hay cuentas conectadas. Empezá por **Cuentas**.")

MODULOS = [
    ("Promociones", [
        ("views/campanas.py", "📣", "Campañas", "Crear, editar y auditar campañas propias y de MeLi.", "SELLER CAMPAIGN"),
        ("views/cargar_promo.py", "🏷️", "Cargar a campaña", "Sumar o quitar modelos-color con precio o %.", "BULK"),
        ("views/descuentos.py", "🔖", "Descuentos", "Descuentos con nombre o individuales, en bloque.", "BULK"),
        ("views/invitaciones.py", "📨", "Invitaciones MeLi", "Aceptar campañas de MeLi donde sos candidato.", "CO-FONDEO"),
    ]),
    ("Precios", [
        ("views/precios.py", "💲", "Precios masivos", "Actualizar por modelo-color con redondeo inteligente.", "BULK"),
        ("views/inconsistencias.py", "⚖️", "Precios distintos", "Detectar e igualar talles con precios diferentes.", "AUDITORÍA"),
    ]),
    ("Catálogo y marca", [
        ("views/contenido.py", "📝", "Contenido SEO / GEO", "Descripciones y ficha técnica con puntaje e IA.", "IA"),
        ("views/proteccion.py", "🛡️", "Protección de marca", "Vendedores sospechosos y registro de denuncias.", "RIESGO"),
        ("views/cuentas.py", "🔑", "Cuentas", "Conectar y administrar las tiendas oficiales.", "CONFIG"),
    ]),
]

for seccion, mods in MODULOS:
    st.markdown(f"### {seccion}")
    cols = st.columns(len(mods) if len(mods) > 2 else 3)
    for col, (page, ic, tit, txt, badge) in zip(cols, mods):
        with col:
            card(ic, tit, txt, badge)
            st.page_link(page, label=f"Abrir {tit} →")
