"""Agregar talles (variantes) a productos existentes a partir de SKU + EAN + stock.

- Asocia cada SKU a su producto por modelo-color (SKU sin el talle).
- Si el SKU ya existe como variante → actualiza EAN y stock.
- Si no existe → crea la variante (talle) copiando precio y precio tachado del producto.
- Producto con variante única ("Default Title") → crea la opción Talle y esa variante pasa a ser el primer talle.
"""
import uuid

import pandas as pd

from .catalog import norm
from .inconsistencias import strip_size
from .shopify import ShopifyClient, ShopifyError

Q_PROD = """query($id: ID!) { product(id: $id) { id title
  options { id name values }
  variants(first: 250) { nodes { id sku barcode title price compareAtPrice
    selectedOptions { name value } inventoryItem { id tracked } } } } }"""
Q_LOC = "{ locations(first: 50, includeInactive: false) { nodes { id name isActive fulfillsOnlineOrders } } }"
M_OPT = """mutation($p: ID!, $o: [OptionCreateInput!]!) { productOptionsCreate(productId: $p, options: $o, variantStrategy: LEAVE_AS_IS) {
  userErrors { field message } product { id } } }"""
M_UPD = """mutation($p: ID!, $v: [ProductVariantsBulkInput!]!) { productVariantsBulkUpdate(productId: $p, variants: $v) {
  productVariants { id inventoryItem { id } } userErrors { field message } } }"""
M_CREATE = """mutation($p: ID!, $v: [ProductVariantsBulkInput!]!) { productVariantsBulkCreate(productId: $p, variants: $v) {
  productVariants { id sku } userErrors { field message } } }"""
M_ACT = """mutation($i: ID!, $l: ID!, $q: Int) { inventoryActivate(inventoryItemId: $i, locationId: $l, available: $q)
  @idempotent(key: "%s") { inventoryLevel { id } userErrors { field message } } }"""
M_SET = """mutation($in: InventorySetQuantitiesInput!) { inventorySetQuantities(input: $in) @idempotent(key: "%s") {
  inventoryAdjustmentGroup { id } userErrors { field message code } } }"""

DEFAULT_OPT = {"title"}


def _err(d: dict) -> str:
    out = []
    for v in (d or {}).values():
        if isinstance(v, dict):
            out += [f"{e.get('field') or ''} {e.get('message')}".strip() for e in v.get("userErrors") or []]
    return "; ".join(out)


def talle_de(sku: str) -> tuple[str | None, str | None]:
    """'K1342233W-KSA02-40' → ('K1342233W-KSA02', '40')."""
    s = str(sku or "").strip().upper()
    base = strip_size(s)
    if not base or base == s:
        return base, None
    return base, s[len(base) + 1:].strip() or None


def parse(texto: str) -> tuple[pd.DataFrame, list[str]]:
    """Texto pegado (3 columnas: SKU, EAN, stock) → DataFrame. Devuelve también las líneas que no pude leer."""
    rows, malas = [], []
    for ln in texto.splitlines():
        if not ln.strip():
            continue
        partes = [x.strip() for x in (ln.split("\t") if "\t" in ln else ln.replace(";", ",").split(","))]
        partes += [""] * (3 - len(partes))
        sku, ean, stock = partes[0], partes[1], partes[2]
        if sku.lower() in ("sku", "codigo", "código"):
            continue   # encabezado
        try:
            q = int(float(stock.replace(".", "").replace(",", "."))) if stock else None
        except ValueError:
            q = None
        if not sku or (stock and q is None):
            malas.append(ln.strip())
            continue
        ean = ean.split(".")[0] if ean.replace(".", "").isdigit() else ean   # 7791234567890.0 de Excel
        rows.append({"sku": sku.upper(), "ean": ean, "stock": q})
    df = pd.DataFrame(rows, columns=["sku", "ean", "stock"]).drop_duplicates("sku", keep="last")
    return df, malas


def asociar(df: pd.DataFrame, P: pd.DataFrame, V: pd.DataFrame) -> pd.DataFrame:
    """Agrega product_id / variante existente / talle / acción a cada fila."""
    por_sku = {str(r["sku"]).upper(): (r["product_id"], r["variant_id"]) for _, r in V.iterrows() if r["sku"]}
    por_cod: dict[str, set] = {}
    for _, r in P.iterrows():
        for c in r["codigos"]:
            por_cod.setdefault(norm(c), set()).add(r["product_id"])
    tit = P.set_index("product_id")["titulo"]
    out = []
    for _, r in df.iterrows():
        base, talle = talle_de(r["sku"])
        fila = {**r.to_dict(), "modelo_color": base, "talle": talle, "product_id": None, "variant_id": None,
                "producto": "", "accion": "", "detalle": ""}
        if r["sku"] in por_sku:
            fila["product_id"], fila["variant_id"] = por_sku[r["sku"]]
            fila["accion"] = "✏️ Actualizar"
        elif not talle:
            fila["accion"], fila["detalle"] = "⚠️ Error", "No pude separar el talle del SKU"
        else:
            pids = por_cod.get(norm(base), set())
            if len(pids) == 1:
                fila["product_id"] = next(iter(pids))
                fila["accion"] = "🆕 Crear talle"
            elif len(pids) > 1:
                fila["accion"], fila["detalle"] = "⚠️ Error", f"El modelo-color está en {len(pids)} productos"
            else:
                fila["accion"], fila["detalle"] = "⚠️ Error", "No encontré el producto de ese modelo-color"
        if fila["product_id"]:
            fila["producto"] = tit.get(fila["product_id"], "")
        out.append(fila)
    return pd.DataFrame(out)


def ubicaciones(key: str) -> list[dict]:
    cli = ShopifyClient(key)
    return [n for n in cli.gql(Q_LOC)["locations"]["nodes"] if n.get("isActive", True)]


def _stock(cli: ShopifyClient, inv_id: str, loc: str, q: int) -> str:
    """Deja el stock disponible en q (activa el ítem en la ubicación si hace falta)."""
    d = cli.gql(M_SET % uuid.uuid4(), {"in": {"name": "available", "reason": "correction",
                                              "quantities": [{"inventoryItemId": inv_id, "locationId": loc,
                                                              "quantity": int(q), "changeFromQuantity": None}]}})
    e = _err(d)
    if e:   # suele ser "no está stockeado en esa ubicación" → activarlo con ese stock
        d2 = cli.gql(M_ACT % uuid.uuid4(), {"i": inv_id, "l": loc, "q": int(q)})
        e = _err(d2) and f"{e} / {_err(d2)}"
    return e


def aplicar_producto(key: str, pid: str, filas: list[dict], loc: str, opcion: str = "Talle") -> list[dict]:
    """Aplica todas las filas de un producto. Devuelve las filas con ok / error / variant_id."""
    cli = ShopifyClient(key)
    p = cli.gql(Q_PROD, {"id": pid})["product"]
    variantes = p["variants"]["nodes"]
    opts = [o for o in p["options"] if o["name"].lower() not in DEFAULT_OPT]
    por_sku = {str(v["sku"] or "").upper(): v for v in variantes}
    ref = variantes[0] if variantes else {}
    for f in filas:
        f["ok"], f["error"] = False, ""

    # opción de talle: la existente con más valores, o la que se llame talle/size
    opt_talle = next((o for o in opts if o["name"].lower() in ("talle", "talla", "size", "tamaño", "medida")), None)
    if not opt_talle and len(opts) == 1:
        opt_talle = opts[0]
    otras = [o for o in opts if opt_talle and o["id"] != opt_talle["id"]]
    if any(len(o["values"]) > 1 for o in otras):
        for f in filas:
            f["error"] = "El producto tiene otra opción con varios valores (ej. color): cargalo a mano"
        return filas
    fijo = [{"optionName": o["name"], "name": o["values"][0]} for o in otras]

    # caso variante única sin opciones → crear opción Talle; la variante única pasa a ser el primer talle
    nuevas = [f for f in filas if f["sku"] not in por_sku]
    if not opts and len(variantes) == 1:
        unica_sku = str(variantes[0]["sku"] or "").upper()
        primera = next((f for f in filas if f["sku"] == unica_sku), None) or (nuevas[0] if nuevas else None)
        if primera:
            d = cli.gql(M_OPT, {"p": pid, "o": [{"name": opcion, "values": [{"name": primera["talle"] or "U"}]}]})
            e = _err(d)
            if e:
                for f in filas:
                    f["error"] = f"No pude crear la opción {opcion}: {e}"
                return filas
            unica = variantes[0]
            por_sku[primera["sku"]] = unica
            nuevas = [f for f in nuevas if f is not primera]
            opt_talle = {"name": opcion}

    # 1) actualizar existentes (SKU, EAN, seguimiento de stock)
    upd = []
    for f in filas:
        v = por_sku.get(f["sku"])
        if not v:
            continue
        x = {"id": v["id"], "inventoryItem": {"sku": f["sku"], "tracked": True}}
        if f.get("ean"):
            x["barcode"] = str(f["ean"])
        upd.append(x)
        f["variant_id"] = v["id"]
    if upd:
        d = cli.gql(M_UPD, {"p": pid, "v": upd})
        e = _err(d)
        inv = {n["id"]: n["inventoryItem"]["id"] for n in (d.get("productVariantsBulkUpdate") or {}).get("productVariants") or []}
        for f in filas:
            if f not in nuevas and f.get("variant_id"):
                if e or f["variant_id"] not in inv:
                    f["error"] = e or "Shopify no devolvió la variante"
                    continue
                if f.get("stock") is not None:
                    f["error"] = _stock(cli, inv[f["variant_id"]], loc, f["stock"])
                f["ok"] = not f["error"]

    # 2) crear talles nuevos
    if nuevas:
        if not opt_talle:
            for f in nuevas:
                f["error"] = "No sé en qué opción va el talle (el producto tiene varias opciones)"
            return filas
        crear = []
        for f in nuevas:
            x = {"optionValues": fijo + [{"optionName": opt_talle["name"], "name": f["talle"]}],
                 "price": ref.get("price") or "0", "inventoryItem": {"sku": f["sku"], "tracked": True}}
            if ref.get("compareAtPrice"):
                x["compareAtPrice"] = ref["compareAtPrice"]
            if f.get("ean"):
                x["barcode"] = str(f["ean"])
            if f.get("stock") is not None:
                x["inventoryQuantities"] = [{"locationId": loc, "availableQuantity": int(f["stock"])}]
            crear.append(x)
        d = cli.gql(M_CREATE, {"p": pid, "v": crear})
        e = _err(d)
        creadas = {str(n["sku"] or "").upper(): n["id"] for n in (d.get("productVariantsBulkCreate") or {}).get("productVariants") or []}
        for f in nuevas:
            f["variant_id"] = creadas.get(f["sku"])
            f["ok"] = bool(f["variant_id"]) and not e
            f["error"] = e if e else ("" if f["variant_id"] else "Shopify no devolvió la variante")
    return filas


def aplicar(key: str, plan: pd.DataFrame, loc: str, opcion: str = "Talle", progress=None) -> pd.DataFrame:
    ok_rows = plan[plan["product_id"].notna()]
    res = []
    grupos = list(ok_rows.groupby("product_id"))
    for i, (pid, g) in enumerate(grupos, 1):
        filas = g.to_dict("records")
        try:
            filas = aplicar_producto(key, pid, filas, loc, opcion)
        except ShopifyError as e:
            for f in filas:
                f["ok"], f["error"] = False, str(e)
        res += filas
        if progress:
            progress(i / len(grupos))
    return pd.DataFrame(res)
