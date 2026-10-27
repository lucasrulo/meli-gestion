"""Menú de la app (una sola fuente: lo usan la navegación y las tarjetas de Inicio).

(archivo, título, ícono material, emoji, descripción, etiqueta)
"""
MENU = {
    "Precios": [
        ("views/omnicanal.py", "Precios omnicanal", "sync_alt", "🔀",
         "Un precio por modelo-color en MeLi y Shopify, en uno o ambos canales.", "MELI + SHOPIFY"),
        ("views/analisis_precios.py", "Análisis de precios", "insights", "📊",
         "Brechas, cobertura y stock entre canales.", "MELI + SHOPIFY"),
        ("views/precios.py", "Precios masivos MeLi", "price_change", "💲",
         "Actualizar por modelo-color con redondeo inteligente.", "MELI"),
        ("views/inconsistencias.py", "Precios distintos MeLi", "balance", "⚖️",
         "Detectar e igualar talles/colores con precios diferentes.", "MELI"),
    ],
    "Promociones MeLi": [
        ("views/campanas.py", "Campañas", "campaign", "📣", "Crear, editar y auditar campañas propias y de MeLi.", "MELI"),
        ("views/cargar_promo.py", "Cargar a campaña", "sell", "🏷️", "Sumar o quitar modelos-color con precio o %.", "MELI"),
        ("views/descuentos.py", "Descuentos", "percent", "🔖", "Descuentos con nombre o individuales, en bloque.", "MELI"),
        ("views/invitaciones.py", "Invitaciones", "mark_email_unread", "📨",
         "Aceptar campañas de MeLi donde sos candidato.", "MELI"),
    ],
    "Catálogo": [
        ("views/shop_catalogo.py", "Catálogo Shopify", "inventory_2", "🗂️",
         "Estados, tags, colecciones (y su Excel por modelo-color) y metacampos en masa.", "SHOPIFY"),
        ("views/clips.py", "Clips y video MeLi", "movie", "🎬",
         "Qué publicaciones tienen clip y cuáles grabar primero.", "MELI"),
    ],
    "Imágenes": [
        ("views/shop_imagenes.py", "Imágenes Shopify", "photo_library", "🖼️",
         "Fotos de productos desde Azure y texto alternativo de productos, banners y archivos.", "SHOPIFY"),
    ],
    "SEO y contenido": [
        ("views/contenido.py", "Descripciones SEO / GEO", "auto_awesome", "📝",
         "Descripciones, ficha técnica y SEO de cada producto con IA, en MeLi y Shopify.", "MELI + SHOPIFY"),
        ("views/shop_seo.py", "SEO y calidad Shopify", "travel_explore", "🔎",
         "Auditoría y SEO de productos, colecciones, páginas y blog, más redirecciones 301.", "SHOPIFY"),
    ],
    "Marca y control": [
        ("views/proteccion.py", "Protección de marca", "shield", "🛡️",
         "Vendedores sospechosos y registro de denuncias.", "MELI"),
        ("views/historial.py", "Historial", "history", "🕑", "Todos los cambios masivos, con deshacer.", "CONTROL"),
        ("views/cuentas.py", "Cuentas", "key", "🔑", "Conectar cuentas de MeLi y tiendas de Shopify.", "CONFIG"),
    ],
}
