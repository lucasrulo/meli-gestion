"""Selector de marca arriba de cada página (en vez de la barra lateral).

- Se muestra como botones (pills) justo debajo del título.
- La elección se recuerda entre páginas y se sincroniza entre canales: si elegís COLUMBIA en una página de MeLi,
  las páginas de Shopify abren en la tienda de Columbia (y al revés).
"""
import streamlit as st

_ACC, _STORE = "_marca_cuenta", "_marca_tienda"


def corto(nombre: str) -> str:
    n = str(nombre or "").split("|")[0]
    for x in (" Argentina", " Sitio Oficial", " Tienda Oficial", " AR"):
        n = n.replace(x, "")
    return n.strip() or str(nombre)


def _barra(label: str, opciones: list[str], fmt, estado_key: str, widget_key: str) -> str:
    actual = st.session_state.get(estado_key)
    if actual not in opciones:
        actual = opciones[0]
        st.session_state[estado_key] = actual
    st.session_state[widget_key] = actual  # el widget arranca con lo último elegido (aunque vengas de otra página)

    def _guardar():
        v = st.session_state.get(widget_key)
        if v:
            st.session_state[estado_key] = v

    with st.container(border=True):
        c1, c2 = st.columns([0.16, 1], vertical_alignment="center")
        c1.markdown(f"<div style='font-size:.78rem;letter-spacing:.08em;color:var(--muted);text-transform:uppercase'>"
                    f"{label}</div>", unsafe_allow_html=True)
        if len(opciones) <= 10:
            c2.pills(label, opciones, format_func=fmt, key=widget_key, on_change=_guardar,
                     label_visibility="collapsed")   # pills: si no entran en una línea, bajan a la siguiente
        else:
            c2.selectbox(label, opciones, format_func=fmt, key=widget_key, on_change=_guardar,
                         label_visibility="collapsed")
    return st.session_state[estado_key]


def elegir_cuenta(accounts: dict) -> str:
    ids = sorted(accounts, key=lambda k: (accounts[k].get("alias") or "").lower())
    fmt = lambda k: accounts[k].get("alias") or accounts[k].get("nickname") or k  # noqa: E731
    uid = _barra("Cuenta MeLi", ids, fmt, _ACC, "w_marca_cuenta")
    alias = (accounts[uid].get("alias") or "").upper()
    try:  # sincroniza la tienda Shopify de la misma marca
        from .shopify import stores
        st_ = stores()
        par = next((k for k, c in st_.items() if str(c.get("meli", "")).upper() == alias and alias), None)
        if par:
            st.session_state[_STORE] = par
    except Exception:  # noqa: BLE001
        pass
    return uid


def elegir_tienda(st_: dict) -> str:
    opts = list(st_)
    key = _barra("Tienda Shopify", opts, lambda k: corto(st_[k]["nombre"]), _STORE, "w_marca_tienda")
    meli = str(st_[key].get("meli") or "").upper()
    if meli:  # sincroniza la cuenta MeLi de la misma marca
        try:
            from .auth import get_token_manager
            acc = get_token_manager().accounts()
            uid = next((u for u, a in acc.items() if (a.get("alias") or "").upper() == meli), None)
            if uid:
                st.session_state[_ACC] = uid
        except Exception:  # noqa: BLE001
            pass
    return key
