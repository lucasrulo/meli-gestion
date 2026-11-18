"""Menú de la app (una sola fuente: lo usan la navegación y las tarjetas de Inicio).

3 portales separados + configuración:
- MercadoLibre: todo lo que se hace solo en MeLi.
- Shopify: todo lo que se hace solo en Shopify.
- MeLi ↔ Shopify: lo que cruza los dos canales (precios, catálogo, descripciones).

(archivo, título, ícono material, emoji, descripción, etiqueta)
"""
MENU = {
    "MercadoLibre": [
        ("views/precios.py", "Precios masivos", "price_change", "💲",
         "Actualizar precios por modelo-color con redondeo inteligente.", "MELI"),
        ("views/inconsistencias.py", "Precios distintos", "balance", "⚖️",
         "Detectar e igualar talles/colores con precios diferentes.", "MELI"),
        ("views/campanas.py", "Campañas", "campaign", "📣", "Crear, editar y auditar campañas propias y de MeLi.", "MELI"),
        ("views/cargar_promo.py", "Cargar a campaña", "sell", "🏷️", "Sumar o quitar modelos-color con precio o %.", "MELI"),
        ("views/descuentos.py", "Descuentos", "percent", "🔖", "Descuentos con nombre o individuales, en bloque.", "MELI"),
        ("views/invitaciones.py", "Invitaciones", "mark_email_unread", "📨",
         "Aceptar campañas de MeLi donde sos candidato.", "MELI"),
        ("views/publicidad.py", "Publicidad (Ads)", "ads_click", "💸",
         "Presupuesto, ROAS objetivo y ajuste automático de Product Ads, en masa.", "MELI"),
        ("views/contenido.py", "Descripciones y ficha", "auto_awesome", "📝",
         "Descripción y ficha técnica optimizadas (SEO/GEO), a mano o con IA.", "MELI"),
        ("views/meli_imagenes.py", "Imágenes", "add_photo_alternate", "📤",
         "Una misma imagen (ej. tabla de talles) a muchas publicaciones.", "MELI"),
        ("views/clips.py", "Clips y video", "movie", "🎬", "Qué publicaciones tienen clip y cuáles grabar primero.", "MELI"),
        ("views/proteccion.py", "Protección de marca", "shield", "🛡️", "Vendedores sospechosos y denuncias.", "MELI"),
    ],
    "Shopify": [
        ("views/shop_productos.py", "Productos y stock", "inventory_2", "📦",
         "Estado y canales, talles con EAN y stock, y metacampos.", "SHOPIFY"),
        ("views/shop_precios.py", "Precios", "sell", "💰",
         "Cargar precios por modelo-color y manejar el precio tachado.", "SHOPIFY"),
        ("views/shop_inconsistencias.py", "Precios distintos", "balance", "⚖️",
         "Talles del mismo modelo-color a distinto precio: igualar (por stock, mayor, menor…).", "SHOPIFY"),
        ("views/shop_colecciones.py", "Tags y colecciones", "label", "🏷️",
         "Tags en masa, limpiar tags sin uso, ver y ordenar colecciones.", "SHOPIFY"),
        ("views/shop_colores.py", "Colores", "palette", "🎨", "Ver y cambiar colores en masa, en todas las tiendas.", "SHOPIFY"),
        ("views/shop_imagenes.py", "Imágenes", "photo_library", "🖼️",
         "Fotos desde Azure y texto alternativo de productos y banners.", "SHOPIFY"),
        ("views/shop_seo.py", "SEO y calidad", "travel_explore", "🔎",
         "Auditoría, SEO de productos, colecciones y páginas, y redirecciones 301.", "SHOPIFY"),
        ("views/shop_clientes.py", "Clientes", "group", "👥", "Buscá clientes por mail y editá sus tags en masa.", "SHOPIFY"),
        ("views/shop_descargas.py", "Descargar productos", "download", "⬇️",
         "Excel de todas las marcas por modelo-color o por SKU, con color y stock.", "SHOPIFY"),
    ],
    "MeLi ↔ Shopify": [
        ("views/analisis_precios.py", "Comparar catálogos", "compare_arrows", "📊",
         "Qué está en un canal y no en el otro, brechas de precio y stock.", "MELI + SHOPIFY"),
        ("views/omnicanal.py", "Precios omnicanal", "sync_alt", "🔀",
         "Un precio por modelo-color aplicado en MeLi, Shopify o ambos.", "MELI + SHOPIFY"),
        ("views/omni_descripciones.py", "Descripciones entre canales", "swap_horiz", "📝",
         "Copiar descripciones de MeLi a Shopify (o al revés) por modelo-color.", "MELI + SHOPIFY"),
    ],
    "Configuración": [
        ("views/cuentas.py", "Cuentas y tiendas", "key", "🔑", "Conectar cuentas de MeLi y tiendas de Shopify.", "CONFIG"),
        ("views/historial.py", "Historial", "history", "🕑", "Todos los cambios masivos, con deshacer.", "CONTROL"),
    ],
}
