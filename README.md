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

## IA para descripciones (opcional · solapa 📝 Contenido SEO)
1. Entrar a https://console.anthropic.com → crear cuenta → **Billing**: cargar crédito (prepago).
2. **Settings → Limits**: poner un límite de gasto mensual (ej. US$ 20) para no tener sorpresas.
3. **API Keys → Create key** → copiar.
4. Streamlit → Settings → Secrets: agregar `ANTHROPIC_API_KEY = "sk-ant-..."` (y opcional `ANTHROPIC_MODEL`).
Sin la key la solapa funciona igual (edición manual y Excel), solo se deshabilitan los botones de IA.

## Shopify (precios omnicanal, análisis y contenido en 2 canales)

### Opción recomendada: botón "Conectar tienda" (como MeLi)
1. dev.shopify.com → **Apps → Create app** → nombre "MeLi Ops".
2. En la versión: **App URL** y **Redirect URLs** = `https://meli-gestion-distrinando.streamlit.app` · *Embed in Shopify admin*: **desactivado** ·
   **Scopes**: `read_products,write_products,read_inventory` → **Release**.
3. **Distribution → Custom distribution** → dominio de la tienda (o la organización Plus, si todas están en la misma) → copiar el link de instalación.
4. **Settings** → copiar Client ID y Client secret → Streamlit Secrets: `SHOPIFY_CLIENT_ID`, `SHOPIFY_CLIENT_SECRET`.
5. App → **Cuentas** → elegir tienda → **🔗 Conectar tienda** → Shopify pide aprobar → volvés conectado. Vinculá la cuenta MeLi y Guardar.

Si las tiendas no están en la misma organización Plus, Shopify obliga una app por tienda: repetí 1-4 y cargá cada par en
`[shopify_apps.<subdominio>]`. Los tokens se guardan en `shopify_tokens.json` (rama `tokens`), nunca en el código.

### Alternativa: token manual en Secrets
En Streamlit → Settings → Secrets, una tabla por tienda (ver `.streamlit/secrets.toml.example`):
```toml
[shopify.kappa]
shop = "xxxx.myshopify.com"
token = "shpat_..."        # o client_id + client_secret si la app es del Dev Dashboard
meli = "KAPPA"             # alias de la cuenta MeLi vinculada
nombre = "Kappa"
vendor = ""                # opcional: tienda compartida (ej "MHW-ar")
```
Scopes necesarios: `read_products`, `write_products` (y `read_inventory` para ver stock).
Probar en **Cuentas → Probar conexión Shopify**.

## Shopify masivo (Catálogo Shopify · SEO y calidad · Historial)
- **Catálogo Shopify**: estados (activo / no listado / borrador / archivado) + publicar en canales, tags, colecciones
  (agregar/quitar/crear por tag), metacampos (valor para todos, por producto o con IA) y fotos desde Azure por código.
- **SEO y calidad**: auditoría con puntaje y arreglos en un clic, SEO title/meta masivo, texto alternativo de fotos
  (reglas o IA que mira la foto) y redirecciones 301.
- **Historial** (Configuración): cada cambio masivo queda guardado con su antes/después y se puede **deshacer**.
- Lectura del catálogo y cambios grandes (≥ 60 productos) usan **Bulk Operations** de Shopify (rápido y sin límite de API).

Permisos (scopes) que necesita la app de Shopify:
`read_products, write_products, read_inventory, write_files, write_online_store_navigation, read_publications, write_publications`
→ Dev Dashboard → tu app → nueva versión con esos scopes → **Release** → en la app: Cuentas → **Conectar tienda** de nuevo en cada tienda.

Secrets opcionales: `AZURE_CATALOGO_URL` (default `https://distriecomm.blob.core.windows.net/catalogo`),
`ANTHROPIC_MODEL_ALT` (default `claude-haiku-4-5`, para texto alternativo).
