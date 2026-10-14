"""Ejecución masiva en paralelo con barra de progreso."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import pandas as pd
import streamlit as st


def run_bulk(rows: list[dict], fn, workers: int = 4, label: str = "Procesando") -> pd.DataFrame:
    """fn(row) hace la llamada; si lanza excepción la fila queda con error."""
    bar = st.progress(0.0, text=f"{label}… 0/{len(rows)}")
    results = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(fn, r): r for r in rows}
        for i, f in enumerate(as_completed(futures), 1):
            r = dict(futures[f])
            try:
                f.result()
                r["resultado"] = "OK"
                r["error"] = ""
            except Exception as e:  # noqa: BLE001
                r["resultado"] = "ERROR"
                r["error"] = str(e)[:500]
            r["procesado"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            results.append(r)
            bar.progress(i / len(rows), text=f"{label}… {i}/{len(rows)}")
    bar.empty()
    return pd.DataFrame(results)
