# meli-gestion · Distrinando

App Streamlit para operar las tiendas oficiales de MercadoLibre de forma masiva:

| Página | Qué hace |
|---|---|
| 🔑 Cuentas | Conecta las 4 cuentas por OAuth, alias, prueba de conexión |
| 📣 Campañas | Lista todas las promos, crea / edita / elimina campañas propias, exporta items |
| 🏷️ Cargar a campaña | modelo-color + % o precio promo → agrega (o quita) en una campaña propia o tradicional de MeLi |
| 🔖 Descuentos | modelo-color + % o precio → aplica (o quita) el descuento por producto con fechas, en bloque |
| 📨 Invitaciones MeLi | Candidatos de campañas de MeLi, filtro por modelo-color y por % que aportás, suma en bloque |
| 💲 Precios masivos | modelo-color + precio → cambia el precio de todos los SKUs/talles de ese modelo-color |

**Carga (Precios, Cargar a campaña, Descuentos):** tabla de 3 columnas *Modelo-color / SKU · Precio actual · Precio nuevo (o promo)*.
Pegás o tipeás los modelos-color y el precio actual se completa solo desde MeLi (con SKUs, publicaciones y alertas:
no encontrado, precios distintos, en promo). El precio nuevo lo cargás a mano, pegado desde Excel, o con
**Aplicar %** a todos (aumento o descuento) con redondeo terminado en 999 / entero / múltiplo de 100 o 1.000.
Búsqueda *Empieza con* (default) trae todos los talles; se ignoran guiones, espacios y mayúsculas.

**Vista previa:** métricas (cargados / encontrados / no encontrados / SKUs / publicaciones), resumen por modelo-color
con precio actual → precio nuevo y % (destildás lo que no quieras), detalle por SKU con link, y lista de no encontrados
descargable. Después: confirmación → ejecución → Excel de resultado con el error exacto de MeLi por fila.

## Setup (una sola vez)

### 1. Repo
Crear repo **privado** `lucasrulo/meli-gestion` y subir todo el contenido de esta carpeta (respetando `meli/`, `views/` y `.streamlit/config.toml`).

### 2. Token de GitHub (para guardar los tokens de MeLi)
GitHub → Settings → Developer settings → Fine-grained tokens → Generate:
- Repository access: **Only select repositories → meli-gestion**
- Permissions → Repository → **Contents: Read and write**

Los tokens de MeLi se guardan en `tokens.json` dentro de la rama `tokens` del mismo repo (se crea sola). Al ser otra rama, cada refresh **no** reinicia la app.

### 3. Deploy en Streamlit Cloud
New app → repo `meli-gestion`, branch `main`, file `app.py`. En *Custom subdomain* poné algo fijo, ej. `meli-gestion-distrinando`.

### 4. App de MercadoLibre (nueva)
developers.mercadolibre.com.ar → Crear aplicación:
- **Redirect URI**: `https://meli-gestion-distrinando.streamlit.app` (exacta, sin `/` final)
- Permisos: lectura y escritura en todo (publicaciones, promociones, ventas) + **offline_access**
- **PKCE: desactivado**

### 5. Secrets en Streamlit
Settings → Secrets → pegar el contenido de `.streamlit/secrets.toml.example` con tus valores. **Poné `APP_PASSWORD`**: la app escribe en MeLi y la URL es pública.

### 6. Conectar cuentas
Página Cuentas → *Conectar cuenta*. Para cada tienda: iniciá sesión en mercadolibre.com.ar con esa cuenta, tocá el botón, autorizá. Luego poné el alias (Columbia, Kappa, …).

## Notas
- Campañas propias se crean como `FLEXIBLE_PERCENTAGE`: cada item con su precio. MeLi valida duración máxima, % mínimo y reglas de precio; si algo no cumple, el error aparece en la fila.
- Precio con descuento_pct se calcula sobre el precio **sin promo** (`original_price` si el item ya tiene una).
- Cambiar el precio de un item con promo activa puede ser rechazado o sacarlo de la promo (MeLi).
- El catálogo de cada cuenta se cachea 1 h; botón 🔄 *Refrescar catálogo* para releer.
