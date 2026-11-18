"""Ayuda de cada página: aparece en el botón «❓ Cómo se usa» al lado del título.

Clave = nombre del archivo de la página (sin .py). Cada entrada: pasos (lista corta) y tips (opcional).
"""

AYUDA: dict[str, dict] = {
    "inicio": {
        "pasos": ["Arriba ves el estado de cada canal: cuentas MeLi, tiendas Shopify e IA.",
                  "Abajo, las herramientas agrupadas en 🟡 MercadoLibre, 🟢 Shopify y 🔀 MeLi ↔ Shopify.",
                  "La marca que elijas en una página queda elegida en todas (y se sincroniza entre MeLi y Shopify)."],
        "tips": ["Todo cambio masivo queda en ⚙️ Historial y la mayoría se puede deshacer."],
    },
    # ------------------------------------------------------------------ MercadoLibre
    "precios": {
        "pasos": ["Elegí la cuenta (marca) arriba.",
                  "Pegá modelo-color o SKU con su precio, o un % para subir/bajar.",
                  "Revisá la vista previa: se marca en rojo lo que cambia más que el % de alerta.",
                  "Confirmá y tocá 🚀 Actualizar."],
        "tips": ["Si una publicación tiene promo activa, MeLi puede rechazar el cambio de precio de lista."],
    },
    "inconsistencias": {
        "pasos": ["Elegí qué considerar el mismo artículo (por defecto: misma publicación + color).",
                  "Elegí la regla (mayor, menor, más frecuente) o escribí el precio a mano.",
                  "Revisá publicación por publicación y aplicá."],
        "tips": ["Si la diferencia es por una promo y no por el precio de lista, comparalo con «Precio de venta»."],
    },
    "campanas": {
        "pasos": ["Elegí la cuenta.", "Mirá tus campañas propias y las de MeLi con su estado y fechas.",
                  "Creá una nueva o editá una existente; después cargá productos desde «Cargar a campaña»."],
    },
    "cargar_promo": {
        "pasos": ["Elegí la campaña.", "Pegá los modelos-color y el precio o % de descuento.",
                  "Revisá la vista previa y confirmá para sumarlos (o quitarlos)."],
        "tips": ["MeLi exige que el precio con descuento esté dentro de los rangos de la campaña: lo que no cumple se avisa."],
    },
    "descuentos": {
        "pasos": ["Elegí la cuenta.", "Pegá los modelos-color y el % o precio final.",
                  "Elegí descuento con nombre o individual, revisá y aplicá."],
    },
    "invitaciones": {
        "pasos": ["Elegí la cuenta.", "Mirá las campañas de MeLi donde tus publicaciones son candidatas.",
                  "Elegí qué publicaciones aceptar (con el precio sugerido o el tuyo) y confirmá."],
    },
    "publicidad": {
        "pasos": ["Elegí la cuenta.", "Mirá las campañas de Product Ads con sus métricas (inversión, ventas, ROAS).",
                  "Cambiá en masa presupuesto, estrategia, ROAS objetivo o el ajuste automático de presupuesto.",
                  "Confirmá: queda en Historial para deshacer."],
        "tips": ["ROAS directo = ventas del anuncio / inversión. ROAS total suma también las ventas asistidas."],
    },
    "contenido": {
        "pasos": ["📊 Analizar: puntúa descripción y ficha técnica de cada publicación (de peor a mejor).",
                  "✏️ Editar: tocá una fila y mejorala a mano o con ✨ IA; ves el puntaje en vivo.",
                  "✨ IA masiva: genera propuestas para las de peor puntaje; aprobás una por una.",
                  "Guardar aplica a todas las variantes de la publicación."],
        "tips": ["Para copiar descripciones a Shopify por Excel: 🔀 MeLi ↔ Shopify → Copiar descripciones."],
    },
    "meli_imagenes": {
        "pasos": ["Subí la imagen (ej. tabla de talles).", "Elegí las publicaciones por categoría o pegando códigos.",
                  "Elegí la posición (al final o 2ª foto) y aplicá."],
        "tips": ["Las publicaciones con el máximo de fotos se omiten. Se puede deshacer desde Historial."],
    },
    "clips": {
        "pasos": ["Elegí la cuenta y leé las publicaciones.", "Ves cuáles tienen clip/video y cuáles no.",
                  "Ordená por ventas para priorizar a cuáles grabarles clip primero."],
    },
    "proteccion": {
        "pasos": ["Buscá publicaciones de terceros con tu marca.", "Revisá las señales (precio bajo, sin factura, fotos copiadas…).",
                  "Marcá las sospechosas y descargá el listado para denunciar."],
    },
    # ------------------------------------------------------------------ Shopify
    "shop_productos": {
        "pasos": ["Elegí la tienda arriba (se lee todo el catálogo en 1–3 min la primera vez).",
                  "🚦 Estado y canales: elegí productos (pegando códigos o con filtros) y cambiá el estado.",
                  "📏 Talles, EAN y stock: pegá SKU · EAN · Stock; crea talles que falten y carga el stock.",
                  "🧩 Metacampos: completá o cambiá metacampos en masa."],
        "tips": ["🔄 Releer catálogo trae los cambios hechos fuera de la app."],
    },
    "shop_precios": {
        "pasos": ["Elegí la tienda.", "💰 Cargar precios: pegá modelo-color · precio (· tachado) y se aplica a todos los talles.",
                  "💲 Precio tachado: % OFF, monto fijo, desde Excel o quitarlo, sin tocar el precio de venta.",
                  "Revisá la vista previa y aplicá."],
        "tips": ["El tachado igual o menor al precio no se muestra en la tienda: la app lo quita o te avisa."],
    },
    "shop_inconsistencias": {
        "pasos": ["Elegí tienda o todas.", "Regla recomendada: precio de los talles CON STOCK (los sin stock quedan desactualizados).",
                  "Revisá variante por variante y aplicá."],
    },
    "shop_colecciones": {
        "pasos": ["🏷️ Tags: agregá, quitá, reemplazá o buscá y reemplazá tags en los productos elegidos.",
                  "🧹 Limpiar tags: ves los tags que no usa ninguna colección y los borrás.",
                  "📚 Ver colecciones: productos de cada colección por modelo-color, con Excel.",
                  "↕️ Ordenar: pegá modelos-color y quedan primeros en la colección, en ese orden."],
    },
    "shop_colores": {
        "pasos": ["Pegá modelos-color (opcional: 2ª columna con el color nuevo).",
                  "Se busca en todas las tiendas y ves el color actual.",
                  "Escribí o pegá la columna de colores nuevos y aplicá."],
        "tips": ["Si el color está en otro lugar (opción o metacampo), cambialo en ⚙️ De dónde se lee el color."],
    },
    "shop_imagenes": {
        "pasos": ["Fotos desde Azure: ves los productos sin foto que tienen foto en el catálogo y las cargás.",
                  "Alt de productos y banners: completá el texto alternativo (con reglas o IA)."],
    },
    "shop_seo": {
        "pasos": ["Auditoría: puntaje de cada producto y qué le falta.", "Completá SEO title y meta description (reglas o IA).",
                  "Colecciones, páginas y blog: mismo flujo.", "Redirecciones 301 en masa."],
    },
    "shop_clientes": {
        "pasos": ["Pegá los mails.", "Ves nombre, apellido, tags, pedidos y gastado.",
                  "Agregá/quitá tags a todos los tildados o editalos en la tabla, revisá y aplicá."],
    },
    "shop_descargas": {
        "pasos": ["Elegí las tiendas y los estados.", "Tildá «Agregar SKU completo» si querés una fila por talle.",
                  "Generá y descargá el Excel (con color, stock, precio y tachado)."],
    },
    # ------------------------------------------------------------------ MeLi ↔ Shopify
    "analisis_precios": {
        "pasos": ["Elegí cuenta(s) MeLi y tiendas Shopify.", "Ves cada modelo-color: solo MeLi, solo Shopify o en ambos, con la brecha de precio.",
                  "Filtrá y ajustá en masa el canal que quieras."],
    },
    "omnicanal": {
        "pasos": ["Pegá modelo-color y precio.", "Elegí dónde aplicarlo: MeLi, Shopify o ambos.",
                  "Revisá la vista previa por canal y aplicá."],
    },
    "omni_descripciones": {
        "pasos": ["Si vas a traer de MeLi, tocá 📥 Leer descripciones.", "Elegí de dónde traer y dónde cargar.",
                  "Bajá el Excel por modelo-color (para BUSCARV), corregí descripcion_nueva y subilo — o aplicá directo.",
                  "Revisá la vista previa y aplicá."],
        "tips": ["Texto plano se convierte a HTML para Shopify; el HTML se limpia a texto para MeLi."],
    },
    # ------------------------------------------------------------------ Configuración
    "cuentas": {
        "pasos": ["MeLi: iniciá sesión en mercadolibre.com.ar con la cuenta de la tienda y tocá ➕ Conectar cuenta.",
                  "Shopify: iniciá sesión en el admin de la tienda y tocá Conectar tienda.",
                  "Asigná alias y la marca MeLi ↔ tienda Shopify para que se sincronicen."],
    },
    "historial": {
        "pasos": ["Elegí un cambio de la lista.", "Mirá el antes y el después.", "Tocá Deshacer si hace falta."],
    },
}
