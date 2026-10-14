"""Lectura de secrets de Streamlit con valores por defecto."""
import streamlit as st

SITE_AUTH_URL = "https://auth.mercadolibre.com.ar/authorization"
TOKEN_URL = "https://api.mercadolibre.com/oauth/token"
API_BASE = "https://api.mercadolibre.com"


def secret(key: str, default=None):
    try:
        return st.secrets[key]
    except Exception:
        return default


def require_secrets(*keys: str) -> None:
    missing = [k for k in keys if not secret(k)]
    if missing:
        st.error(
            "Faltan secrets en Streamlit: " + ", ".join(missing)
            + ". Cargalos en Settings → Secrets (ver .streamlit/secrets.toml.example)."
        )
        st.stop()
