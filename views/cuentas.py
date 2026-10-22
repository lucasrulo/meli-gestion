import time
from datetime import datetime

import pandas as pd
import streamlit as st

from meli.theme import hero

from meli.auth import get_token_manager

hero("Cuentas", "Conexión segura de tus tiendas oficiales de MercadoLibre.", "CONFIGURACIÓN")

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


# ---------------------------------------------------------------- Shopify
from meli import shopify as sh  # noqa: E402
from meli import shopify_auth as sa  # noqa: E402

st.divider()
st.subheader("Tiendas Shopify")

if sa.oauth_enabled():
    auth = sa.get_shopify_auth()
    st.caption("Iniciá sesión en el admin de Shopify de la tienda, elegila y tocá **Conectar tienda**: "
               "Shopify te pide aprobar los permisos y volvés acá conectado. El link vale 15 minutos.")
    opciones = {d["shop"]: d["nombre"] for d in sh.DEFAULT_STORES.values()}
    c1, c2, c3 = st.columns([1.3, 1.3, 1])
    elegida = c1.selectbox("Tienda", list(opciones) + ["otra"], key="shp_sel",
                           format_func=lambda x: f"{opciones[x]} · {x}" if x in opciones else "Otra (escribir dominio)")
    otra = c2.text_input("Dominio", key="shp_otra", placeholder="mitienda.myshopify.com",
                         disabled=elegida != "otra")
    dominio = sa.norm_shop(otra if elegida == "otra" else elegida)
    c3.write("")
    if dominio:
        try:
            c3.link_button("🔗 Conectar tienda", auth.authorize_url(dominio), type="primary", width="stretch")
        except sa.ShopifyAuthError as e:
            c3.error(str(e))
    else:
        c3.button("🔗 Conectar tienda", disabled=True, width="stretch")

    con = auth.connected()
    if con:
        st.markdown("**Conectadas por app**")
        aliases = [""] + sorted({(a.get("alias") or "").upper() for a in accounts.values() if a.get("alias")})
        for shop, rec in con.items():
            with st.expander(f"✅ {rec.get('nombre')} · {shop} · conectada {rec.get('connected_at', '')}"):
                e1, e2, e3, e4 = st.columns([1.2, 1.2, 1, 1])
                nom = e1.text_input("Nombre", rec.get("nombre", ""), key=f"shp_n_{shop}")
                meli_v = (rec.get("meli") or "").upper()
                mel = e2.selectbox("Cuenta MeLi vinculada", aliases if meli_v in aliases else aliases + [meli_v],
                                   index=(aliases if meli_v in aliases else aliases + [meli_v]).index(meli_v),
                                   key=f"shp_m_{shop}", format_func=lambda x: x or "— todas —")
                ven = e3.text_input("Vendor (opcional)", rec.get("vendor", ""), key=f"shp_v_{shop}",
                                    help="Para tiendas compartidas: ej. MHW-ar o Sorel-ar")
                e4.write("")
                if e4.button("Guardar", key=f"shp_g_{shop}", width="stretch"):
                    auth.set_meta(shop, nombre=nom, meli=mel, vendor=ven)
                    st.rerun()
                st.caption(f"Permisos: `{rec.get('scope')}`")
                if st.checkbox(f"Confirmo desconectar {shop}", key=f"shp_dx_{shop}"):
                    if st.button("Desconectar", key=f"shp_d_{shop}"):
                        auth.remove(shop)
                        st.rerun()
else:
    st.info("Para conectar tiendas con un botón (como MeLi) cargá `SHOPIFY_CLIENT_ID` y `SHOPIFY_CLIENT_SECRET` "
            "de tu app de Shopify en los Secrets (ver README → Shopify por app).")

stores = sh.stores()
if stores:
    st.markdown("**Tiendas disponibles en la app**")
    st.dataframe(pd.DataFrame([{
        "clave": k, "tienda": c["nombre"], "dominio": c["shop"], "vendor (filtro)": c.get("vendor") or "—",
        "cuenta MeLi vinculada": c.get("meli") or "todas",
        "acceso": "app (botón)" if c.get("oauth") else ("token en secrets" if c.get("token") else
                                                         ("client credentials" if c.get("client_id") else "⚠️ falta")),
    } for k, c in stores.items()]), hide_index=True, width="stretch")
    if st.button("Probar conexión Shopify"):
        for k in stores:
            try:
                st.success(f"{stores[k]['nombre']}: OK · {sh.ShopifyClient(k).shop_name()}")
            except Exception as e:  # noqa: BLE001
                st.error(f"{stores[k]['nombre']}: {e}")
else:
    hint = sh.secret_names_hint()
    if hint:
        st.caption("Secrets que veo con nombre parecido (solo nombres): " + ", ".join(f"`{h}`" for h in hint))
