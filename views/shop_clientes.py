"""Clientes Shopify: pegar mails → ver nombre, apellido, mail y tags → agregar / quitar tags en masa."""
import re
from datetime import datetime

import pandas as pd
import streamlit as st

from meli import shop_ops as ops
from meli.excel import to_xlsx
from meli.shop_ui import pick_store, progreso
from meli.shopify import ShopifyClient, ShopifyError, stores
from meli.theme import hero
from meli.ui import caja_texto

hero("Clientes Shopify", "Pegá un listado de mails: te traigo nombre, apellido y tags, y podés agregar o quitar tags en masa.",
     "SHOPIFY · CLIENTES")
tienda = pick_store()
nombre = stores()[tienda]["nombre"]

MAIL = re.compile(r"[\w.+'-]+@[\w-]+(?:\.[\w-]+)+")
Q = """query($q: String!, $c: String) { customers(first: 250, query: $q, after: $c) {
         pageInfo { hasNextPage endCursor }
         nodes { id firstName lastName tags numberOfOrders createdAt
                 defaultEmailAddress { emailAddress } amountSpent { amount } } } }"""


@st.cache_data(ttl=300, show_spinner=False)
def buscar(key: str, mails: tuple[str, ...], nonce) -> pd.DataFrame:
    cli, rows = ShopifyClient(key), []
    for i in range(0, len(mails), 25):
        lote = mails[i:i + 25]
        q = " OR ".join(f'email:"{m}"' for m in lote)
        cur = None
        while True:
            d = cli.gql(Q, {"q": q, "c": cur})["customers"]
            for n in d["nodes"]:
                rows.append({"id": n["id"], "email": ((n.get("defaultEmailAddress") or {}).get("emailAddress") or "").lower(),
                             "nombre": n.get("firstName") or "", "apellido": n.get("lastName") or "",
                             "tags": list(n.get("tags") or []), "pedidos": int(n.get("numberOfOrders") or 0),
                             "gastado": float((n.get("amountSpent") or {}).get("amount") or 0),
                             "alta": (n.get("createdAt") or "")[:10]})
            if not d["pageInfo"]["hasNextPage"]:
                break
            cur = d["pageInfo"]["endCursor"]
    df = pd.DataFrame(rows, columns=["id", "email", "nombre", "apellido", "tags", "pedidos", "gastado", "alta"])
    return df[df["email"].isin(set(mails))].drop_duplicates("id")   # la búsqueda de Shopify es aproximada: filtro exacto


txt = caja_texto("Mails de clientes (uno por línea, o pegados desde Excel / separados por coma)", "cli_mails",
                 "🔎 Buscar clientes", placeholder="juan.perez@gmail.com\nmaria@hotmail.com\n…")
mails = tuple(dict.fromkeys(m.lower() for m in MAIL.findall(txt)))
if not mails:
    st.info("Pegá uno o más mails para empezar.")
    st.stop()

nk = f"cli_nonce_{tienda}"
try:
    with st.spinner(f"Buscando {len(mails)} clientes en {nombre}…"):
        df = buscar(tienda, mails, st.session_state.get(nk, 0))
except ShopifyError as e:
    msg = str(e)
    st.error(msg)
    if "customer" in msg.lower() or "access" in msg.lower() or "scope" in msg.lower():
        st.info("La app de Shopify necesita permiso a clientes: **read_customers / write_customers** y acceso a "
                "**datos protegidos de clientes** (Nombre y Email). Ver pasos en *Cuentas* / README.")
    st.stop()

faltan = [m for m in mails if m not in set(df["email"])]
m1, m2, m3 = st.columns(3)
m1.metric("Mails pegados", len(mails))
m2.metric("Clientes encontrados", len(df))
m3.metric("No encontrados", len(faltan))
if faltan:
    with st.expander(f"⚠️ {len(faltan)} mails no existen como clientes en {nombre}"):
        st.code("\n".join(faltan), language=None)
if df.empty:
    st.stop()

# ---------------------------------------------------------------- tabla editable
st.subheader("1 · Clientes")
todos_tags = sorted({t for ts in df["tags"] for t in ts})
vista = df.copy()
vista.insert(0, "✔", True)
vista["tags_txt"] = vista["tags"].map(", ".join)
ed = st.data_editor(
    vista[["✔", "email", "nombre", "apellido", "tags_txt", "pedidos", "gastado", "alta", "id"]],
    hide_index=True, width="stretch", height=min(40 + 36 * len(vista), 460),
    key=f"cli_ed_{tienda}_{hash(mails)}_{st.session_state.get(nk, 0)}",
    column_order=["✔", "email", "nombre", "apellido", "tags_txt", "pedidos", "gastado", "alta"],
    disabled=["email", "nombre", "apellido", "pedidos", "gastado", "alta", "id"],
    column_config={"✔": st.column_config.CheckboxColumn(width="small"),
                   "email": st.column_config.TextColumn("Mail", width="medium"),
                   "tags_txt": st.column_config.TextColumn("Tags (editable, separados por coma)", width="large"),
                   "gastado": st.column_config.NumberColumn("Gastado", format="$ %.0f"),
                   "alta": "Alta"})
st.caption("Podés editar los tags de un cliente puntual directamente en la tabla, o usar las acciones de abajo para "
           "todos los tildados.")
st.download_button("⬇️ Descargar Excel", to_xlsx(df.assign(tags=df["tags"].map(", ".join)).drop(columns=["id"])),
                   f"clientes_{tienda}_{datetime.now():%Y%m%d_%H%M}.xlsx")

# ---------------------------------------------------------------- acciones en masa
st.subheader("2 · Agregar o quitar tags a los tildados")
split = lambda s: [t.strip() for t in str(s or "").split(",") if t.strip()]  # noqa: E731
c1, c2 = st.columns(2)
add = c1.multiselect("➕ Agregar tags", todos_tags, key="cli_add", accept_new_options=True,
                     placeholder="Elegí o escribí uno nuevo (Enter)")
rem = c2.multiselect("➖ Quitar tags", todos_tags, key="cli_rem", placeholder="Elegí de los que ya tienen")

orig = df.set_index("id")["tags"]
filas = []
for _, r in ed.iterrows():
    antes = list(orig.get(r["id"], []))
    nuevos = split(r["tags_txt"])
    if r["✔"]:
        nuevos = nuevos + [t for t in add if t.lower() not in {x.lower() for x in nuevos}]
        nuevos = [t for t in nuevos if t.lower() not in {x.lower() for x in rem}]
    if sorted(map(str.lower, nuevos)) != sorted(map(str.lower, antes)):
        filas.append({"id": r["id"], "label": r["email"], "antes": antes, "despues": nuevos})

if not filas:
    st.caption("Sin cambios todavía.")
    st.stop()
prev = pd.DataFrame([{"Mail": f["label"], "Tags antes": ", ".join(f["antes"]), "Tags después": ", ".join(f["despues"]),
                      "Agrega": ", ".join(t for t in f["despues"] if t not in f["antes"]),
                      "Quita": ", ".join(t for t in f["antes"] if t not in f["despues"])} for f in filas])
st.dataframe(prev, hide_index=True, width="stretch", height=min(40 + 36 * len(prev), 360))

c1, c2 = st.columns([2, 1], vertical_alignment="center")
ok = c1.checkbox(f"Confirmo cambiar los tags de {len(filas)} cliente(s)", key=f"cli_ok_{len(filas)}")
if c2.button("👥 Aplicar tags", type="primary", disabled=not ok, key="cli_go", width="stretch"):
    res = ops.aplicar(tienda, "cliente_tags", filas, f"{nombre}: tags de {len(filas)} clientes"
                      + (f" (+{', '.join(add)})" if add else "") + (f" (−{', '.join(rem)})" if rem else ""),
                      progress=progreso("Actualizando clientes…"))
    ops.mostrar_resultado(res)
    st.session_state[nk] = st.session_state.get(nk, 0) + 1
    buscar.clear()
