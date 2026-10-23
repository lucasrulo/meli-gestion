"""Historial de cambios masivos + deshacer.

Cada operación se guarda en la rama `tokens` del repo:
  historial/index.json      → resumen de las últimas 500 operaciones
  historial/<id>.json       → detalle (antes/después por fila) para poder deshacer
"""
import time
import uuid

import streamlit as st

from .token_store import GitHubTokenStore

MAX_INDEX = 500


def _store(path: str) -> GitHubTokenStore:
    s = GitHubTokenStore()
    s.path = path
    return s


def usuario() -> str:
    try:
        u = getattr(st, "user", None)
        if u is not None and u.get("email"):
            return str(u.get("email"))
    except Exception:  # noqa: BLE001
        pass
    return st.session_state.get("_usuario", "") or "app"


def registrar(canal: str, tienda: str, accion: str, descripcion: str, filas: list[dict],
              meta: dict | None = None, reversible: bool = True, deshace: str | None = None) -> str | None:
    """filas: [{"id", "label", "antes", "despues", "ok", "error"}]. Devuelve el id de la operación.
    Nunca rompe la operación principal: si GitHub falla, avisa y sigue."""
    if not filas:
        return None
    op_id = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
    ok = sum(1 for f in filas if f.get("ok"))
    entry = {
        "id": op_id, "fecha": time.strftime("%Y-%m-%d %H:%M:%S"), "usuario": usuario(), "canal": canal,
        "tienda": tienda, "accion": accion, "descripcion": descripcion, "filas": filas, "meta": meta or {},
        "reversible": reversible, "deshace": deshace,
    }
    resumen = {k: entry[k] for k in ("id", "fecha", "usuario", "canal", "tienda", "accion", "descripcion",
                                     "reversible", "deshace")}
    resumen.update({"total": len(filas), "ok": ok, "deshecha_por": None})
    try:
        _store(f"historial/{op_id}.json").update(lambda d: entry, f"historial {op_id}")

        def fn(d):
            ops = d.get("ops", [])
            ops.insert(0, resumen)
            if deshace:
                for o in ops:
                    if o["id"] == deshace:
                        o["deshecha_por"] = op_id
            d["ops"] = ops[:MAX_INDEX]
            return d
        _store("historial/index.json").update(fn, f"historial index {op_id}")
    except Exception as e:  # noqa: BLE001
        st.warning(f"El cambio se hizo, pero no pude guardarlo en el historial: {e}")
        return None
    return op_id


def listar() -> list[dict]:
    try:
        d, _ = _store("historial/index.json").load()
    except Exception as e:  # noqa: BLE001
        st.error(f"No pude leer el historial: {e}")
        return []
    return d.get("ops", [])


def detalle(op_id: str) -> dict:
    d, _ = _store(f"historial/{op_id}.json").load()
    return d
