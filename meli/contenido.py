"""Contenido de publicaciones: descripción + ficha técnica (atributos), puntaje SEO/GEO e IA opcional (Claude)."""
import json
import re
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import requests

from .api import MeliClient, MeliError
from .catalog import multiget

# ---------------------------------------------------------------- MeLi: descripción
def get_description(client: MeliClient, item_id: str) -> str:
    try:
        r = client.get(f"/items/{item_id}/description")
    except MeliError as e:
        if e.status == 404:
            return ""
        raise
    return (r or {}).get("plain_text") or "" if isinstance(r, dict) else ""


def set_description(client: MeliClient, item_id: str, text: str) -> dict:
    body = {"plain_text": text}
    try:
        return client.put(f"/items/{item_id}/description", json=body, params={"api_version": "2"})
    except MeliError as e:
        if e.status == 404:  # no tenía descripción → se crea
            return client.post(f"/items/{item_id}/description", json=body)
        raise


def set_attributes(client: MeliClient, item_id: str, attrs: dict[str, str]) -> dict:
    """attrs: {ATTR_ID: value_name}"""
    body = {"attributes": [{"id": k, "value_name": str(v)} for k, v in attrs.items() if str(v).strip()]}
    return client.put(f"/items/{item_id}", json=body)


# ---------------------------------------------------------------- MeLi: atributos de categoría
_CAT_CACHE: dict[str, list] = {}
SKIP_TAGS = {"read_only", "hidden", "fixed", "variation_attribute", "others", "inferred"}
SKIP_IDS = {"SELLER_SKU", "GTIN", "ITEM_CONDITION", "SIZE", "COLOR", "MAIN_COLOR", "FILTRABLE_SIZE",
            "SIZE_GRID_ID", "SIZE_GRID_ROW_ID", "PRODUCT_DATA_SOURCE", "EMPTY_GTIN_REASON"}


def category_attributes(client: MeliClient, cat_id: str) -> list[dict]:
    if cat_id in _CAT_CACHE:
        return _CAT_CACHE[cat_id]
    try:
        attrs = client.get(f"/categories/{cat_id}/attributes")
    except MeliError:
        attrs = []
    out = []
    for a in attrs if isinstance(attrs, list) else []:
        tags = a.get("tags") or {}
        if a.get("id") in SKIP_IDS or any(tags.get(t) for t in SKIP_TAGS):
            continue
        out.append({
            "id": a.get("id"),
            "nombre": a.get("name"),
            "tipo": a.get("value_type"),
            "requerido": bool(tags.get("required") or tags.get("catalog_required")),
            "valores": [v.get("name") for v in (a.get("values") or [])][:60],
        })
    _CAT_CACHE[cat_id] = out
    return out


def item_attr_values(item: dict) -> dict[str, str]:
    return {a.get("id"): a.get("value_name") for a in (item.get("attributes") or []) if a.get("value_name")}


# ---------------------------------------------------------------- análisis
def _tokens(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-záéíóúñü0-9]+", (s or "").lower()) if len(w) > 3}


def seo_score(title: str, desc: str, filled: int, total: int) -> tuple[int, list[str]]:
    pts, notas = 0, []
    n = len(desc or "")
    if n == 0:
        notas.append("sin descripción")
    elif n < 300:
        pts += 10
        notas.append("descripción muy corta")
    elif n < 800:
        pts += 25
        notas.append("descripción corta")
    else:
        pts += 40
    lines = [l for l in (desc or "").splitlines() if l.strip()]
    if len(lines) >= 6:
        pts += 10
    elif n:
        notas.append("sin estructura (secciones/viñetas)")
    tt = _tokens(title)
    if tt:
        cov = len(tt & _tokens(desc)) / len(tt)
        pts += round(cov * 20)
        if cov < 0.6:
            notas.append("la descripción no repite las palabras clave del título")
    if total:
        ratio = filled / total
        pts += round(ratio * 30)
        if ratio < 0.8:
            notas.append(f"ficha técnica incompleta ({filled}/{total})")
    else:
        pts += 15
    if re.search(r"\?", desc or ""):
        pass
    elif n:
        notas.append("sin preguntas frecuentes (GEO)")
    return min(pts, 100), notas


def parse_ficha(ficha: str) -> tuple[int, int]:
    try:
        a, b = str(ficha).split("/")
        return int(a), int(b)
    except Exception:
        return 0, 0


def comparar(title: str, desc_actual: str, desc_nueva: str, filled_act: int, filled_new: int, total: int) -> dict:
    """Puntaje antes y después + qué mejoras quedan pendientes en la versión nueva."""
    s0, _ = seo_score(title, desc_actual, filled_act, total)
    s1, pend = seo_score(title, desc_nueva, filled_new, total)
    return {"antes": s0, "despues": s1, "delta": s1 - s0, "pendientes": pend}


def _foto_url(it: dict) -> str:
    pics = it.get("pictures") or []
    u = (pics[0].get("secure_url") or pics[0].get("url")) if pics else it.get("thumbnail")
    return (u or "").replace("http://", "https://")


def analyze(client: MeliClient, rep_ids: list[str], progress=None) -> pd.DataFrame:
    items = {it["id"]: it for it in multiget(client, rep_ids)}
    with ThreadPoolExecutor(max_workers=6) as ex:
        descs = dict(zip(rep_ids, ex.map(lambda i: get_description(client, i) if i in items else "", rep_ids)))
    rows = []
    for n, iid in enumerate(rep_ids, 1):
        it = items.get(iid)
        if not it:
            continue
        cat = category_attributes(client, it.get("category_id"))
        vals = item_attr_values(it)
        faltan = [a for a in cat if a["id"] not in vals]
        filled = len(cat) - len(faltan)
        score, notas = seo_score(it.get("title"), descs.get(iid, ""), filled, len(cat))
        rows.append({
            "item_id": iid,
            "categoria": it.get("category_id"),
            "score": score,
            "largo_desc": len(descs.get(iid, "")),
            "ficha": f"{filled}/{len(cat)}",
            "faltan_requeridos": ", ".join(a["nombre"] for a in faltan if a["requerido"])[:150],
            "faltan": ", ".join(a["nombre"] for a in faltan)[:200],
            "mejoras": " · ".join(notas),
            "descripcion": descs.get(iid, ""),
            "foto": _foto_url(it),
        })
        if progress:
            progress(n / len(rep_ids))
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- IA (Claude)
PRECIOS = {  # USD por millón de tokens (entrada, salida)
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-sonnet-4-5": (3.0, 15.0),
    "claude-sonnet-4-6": (3.0, 15.0),
}

SYSTEM = """Sos un especialista en contenido para MercadoLibre Argentina (SEO del buscador de MeLi y GEO: que asistentes
de IA y buscadores entiendan y citen la publicación). Escribís en español rioplatense neutro, claro y vendedor sin exagerar.

Reglas de MercadoLibre (obligatorias):
- Solo texto plano: sin HTML, sin markdown (#, **), sin emojis.
- Prohibido: links, teléfonos, emails, redes sociales, mencionar otros sitios o marcas competidoras, precios,
  cuotas, envíos, descuentos o promociones.
- No inventes datos: usá SOLO la información provista (título, atributos, descripción actual). Si un dato no está, no lo pongas.

Estructura de la descripción:
1. Párrafo inicial (2-3 oraciones) con marca, modelo, tipo de producto, color y uso principal (palabras clave del título).
2. CARACTERÍSTICAS: viñetas con "- " (materiales, tecnología, suela, cierre, etc. solo si están en los datos).
3. IDEAL PARA: usos y ocasiones.
4. TALLES Y CALCE: solo si hay datos.
5. PREGUNTAS FRECUENTES: 3 a 5 pares "P: ... / R: ..." con respuestas basadas en los datos (GEO).
6. Cierre breve: producto original de tienda oficial.
Largo: 1200 a 2500 caracteres.

Atributos: proponé valores SOLO para los atributos faltantes que se deduzcan con certeza de los datos.
Si el atributo tiene valores posibles, usá exactamente uno de ellos.

Respondé ÚNICAMENTE con JSON válido:
{"descripcion": "...", "atributos": [{"id": "ATTR_ID", "valor": "...", "motivo": "de dónde sale"}]}"""


def ai_suggest(api_key: str, model: str, item: dict, desc: str, cat_attrs: list[dict],
               extra: str = "") -> tuple[dict, float]:
    vals = item_attr_values(item)
    faltan = [{"id": a["id"], "nombre": a["nombre"], "valores_posibles": a["valores"][:25]}
              for a in cat_attrs if a["id"] not in vals]
    datos = {
        "titulo": item.get("title"),
        "categoria": item.get("category_id"),
        "atributos_cargados": {a.get("name") or a.get("id"): a.get("value_name")
                               for a in (item.get("attributes") or []) if a.get("value_name")},
        "atributos_faltantes": faltan[:40],
        "descripcion_actual": (desc or "")[:6000],
    }
    user = "Datos de la publicación:\n" + json.dumps(datos, ensure_ascii=False, indent=1)
    if extra.strip():
        user += "\n\nIndicaciones adicionales del vendedor:\n" + extra.strip()
    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
        json={"model": model, "max_tokens": 3000, "system": SYSTEM,
              "messages": [{"role": "user", "content": user}]},
        timeout=120,
    )
    if r.status_code != 200:
        raise RuntimeError(f"Claude API {r.status_code}: {r.text[:300]}")
    body = r.json()
    text = "".join(b.get("text", "") for b in body.get("content", []) if b.get("type") == "text")
    m = re.search(r"\{.*\}", text, re.S)
    data = json.loads(m.group(0)) if m else {"descripcion": text, "atributos": []}
    data["descripcion"] = limpiar(data.get("descripcion", ""))
    u = body.get("usage") or {}
    pin, pout = PRECIOS.get(model, (3.0, 15.0))
    costo = u.get("input_tokens", 0) / 1e6 * pin + u.get("output_tokens", 0) / 1e6 * pout
    return data, costo


def limpiar(txt: str) -> str:
    """Saca lo que MeLi no acepta en descripciones: HTML, markdown, emojis, links, mails, teléfonos."""
    t = re.sub(r"<[^>]+>", "", txt or "")
    t = re.sub(r"[*#`_]{1,3}", "", t)
    t = re.sub(r"https?://\S+|www\.\S+", "", t)
    t = re.sub(r"\S+@\S+\.\S+", "", t)
    t = re.sub(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", "", t)
    t = re.sub(r"[ \t]+\n", "\n", t)
    return re.sub(r"\n{3,}", "\n\n", t).strip()


def estimar_costo(n: int, model: str) -> float:
    pin, pout = PRECIOS.get(model, (3.0, 15.0))
    return n * (2500 / 1e6 * pin + 900 / 1e6 * pout)


# ---------------------------------------------------------------- Shopify (HTML + SEO)
def shop_score(title: str, html: str, seo_title: str, seo_desc: str) -> tuple[int, list[str]]:
    """Mismo criterio que MeLi para el cuerpo (70 pts) + SEO title/meta description (30 pts)."""
    from .shopify import html_to_text
    base, notas = seo_score(title, html_to_text(html), 0, 0)  # sin ficha técnica: 15 pts fijos
    base -= 15
    pts = base
    tl, dl = len(seo_title or ""), len(seo_desc or "")
    if 30 <= tl <= 70:
        pts += 15
    else:
        notas.append("SEO title vacío" if not tl else f"SEO title de {tl} caracteres (ideal 30–70)")
        pts += 5 if tl else 0
    if 70 <= dl <= 160:
        pts += 15
    else:
        notas.append("meta description vacía" if not dl else f"meta description de {dl} caracteres (ideal 70–160)")
        pts += 5 if dl else 0
    if html and "<h2" not in html.lower():
        notas.append("sin subtítulos H2")
    return max(0, min(pts, 100)), [n for n in notas if not n.startswith("ficha")]


SYSTEM_SHOP = """Sos especialista en SEO para e-commerce y GEO (que buscadores e IA entiendan y citen la página) para una
tienda oficial de marca en Argentina (Shopify). Español rioplatense neutro.
Reglas: no inventes datos (usá solo lo provisto); no menciones precios, cuotas, envíos ni promociones; sin emojis.
Devolvé HTML limpio solo con <h2>, <h3>, <p>, <ul>, <li>, <strong> (sin estilos, sin scripts, sin links).
Estructura: párrafo inicial con marca + modelo + tipo + color + uso; <h2>Características</h2> con lista;
<h2>Ideal para</h2>; <h2>Preguntas frecuentes</h2> con 3-5 <h3>pregunta</h3><p>respuesta</p>.
SEO title: 45-65 caracteres, con marca, modelo y tipo de producto. Meta description: 130-155 caracteres, persuasiva.
Respondé ÚNICAMENTE JSON: {"html": "...", "seo_title": "...", "seo_description": "..."}"""


def ai_suggest_shopify(api_key: str, model: str, titulo: str, base_text: str, atributos: dict, extra: str = ""):
    datos = {"titulo": titulo, "atributos": atributos, "descripcion_base": (base_text or "")[:6000]}
    user = "Datos del producto:\n" + json.dumps(datos, ensure_ascii=False, indent=1)
    if extra.strip():
        user += "\n\nIndicaciones adicionales:\n" + extra.strip()
    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
        json={"model": model, "max_tokens": 3500, "system": SYSTEM_SHOP, "messages": [{"role": "user", "content": user}]},
        timeout=120,
    )
    if r.status_code != 200:
        raise RuntimeError(f"Claude API {r.status_code}: {r.text[:300]}")
    body = r.json()
    text = "".join(b.get("text", "") for b in body.get("content", []) if b.get("type") == "text")
    m = re.search(r"\{.*\}", text, re.S)
    data = json.loads(m.group(0)) if m else {"html": text}
    data["html"] = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", data.get("html", ""), flags=re.S | re.I)
    u = body.get("usage") or {}
    pin, pout = PRECIOS.get(model, (3.0, 15.0))
    return data, u.get("input_tokens", 0) / 1e6 * pin + u.get("output_tokens", 0) / 1e6 * pout
