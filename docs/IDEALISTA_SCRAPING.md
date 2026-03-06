# Cómo obtener imágenes y datos de Idealista

Idealista protege sus páginas con **DataDome WAF** y anti-bot, por lo que una petición HTTP directa (`requests` + BeautifulSoup) suele devolver **403 Forbidden** desde muchos entornos (datacenter, CI, etc.). En la app, si la extracción directa falla, se puede usar una API de terceros o pegar URLs de imágenes a mano.

## Opciones que funcionan

### 1. **ZenRows – API de datos de Idealista** (recomendada si tienes API key)

- **Documentación:** https://docs.zenrows.com/scraper-apis/get-started/idealista-property  
- **Qué hace:** Devuelve JSON con datos del anuncio, incluido el array `property_images` con las URLs de las fotos.
- **Uso:**  
  - Obtener el ID del inmueble desde la URL: `https://www.idealista.com/inmueble/110670317/` → ID = `110670317`.  
  - Llamada:  
    `GET https://realestate.api.zenrows.com/v1/targets/idealista/properties/{propertyId}?apikey=TU_ZENROWS_API_KEY`  
  - También aceptan el parámetro `url` con la URL completa del anuncio.
- **En esta app:** Si en los secrets (Streamlit Cloud o `.streamlit/secrets.toml`) configuras `ZENROWS_API_KEY`, al pulsar «Obtener fotos desde anuncio» en un inmueble con URL de Idealista se usará esta API para obtener las imágenes cuando la extracción directa falle o no devuelva resultados.

### 2. **Apify – Actors para Idealista**

- **Por URL de anuncio:**  
  - Actor: **Idealista Property Listing Scraper**  
  - https://apify.com/duncan01/idealista-property-listing-scraper  
  - Entrada: `startUrls: [{ "url": "https://www.idealista.com/inmueble/110670317/" }]`  
  - Salida: datos del inmueble, imágenes, características, contacto, etc.  
  - Usa proxies residenciales y evita bloqueos.
- **Por búsqueda:**  
  - Actor: **Idealista Scraper** (igolaizola, axlymxp, lukass, etc.)  
  - Para listados por zona/tipo; no pensado para una sola URL.
- **Uso desde Python:** `pip install apify-client` y ejecutar el actor con el token de Apify. Tiene coste por ejecución.

### 3. **ScraperAPI**

- https://www.scraperapi.com/solutions/realestate-data-collection/idealista-scraper  
- Servicio que gestiona proxies, CAPTCHAs y anti-bot.  
- Integración vía su API (no es un paquete específico de Idealista).  
- De pago según volumen de peticiones.

### 4. **idealista-scraper (PyPI)**

- Paquete: `pip install idealista-scraper`  
- Pensado para **búsquedas** (por localidad, tipo, páginas), no para una sola URL.  
- Usa **Scrapfly** por debajo (clave API).  
- Incluye descarga de imágenes a S3, salida JSONL, sesiones reanudables.

### 5. **Extracción directa (sin API)**

- Solo funciona cuando la petición **no** recibe 403 (por ejemplo desde tu red de casa).  
- En la app: se parsea el HTML buscando `<img>`, `data-src`, y patrones de URL de Idealista (`img*.idealista.com`, etc.).  
- Si Idealista devuelve 403, verás el mensaje de error y podrás usar ZenRows (con API key) o pegar URLs de imágenes manualmente.

## Resumen práctico en esta app

| Situación | Qué hacer |
|-----------|-----------|
| Tienes **ZenRows API key** | Añade `ZENROWS_API_KEY` en secrets; la app usará la API de ZenRows para URLs de Idealista y obtendrá las imágenes automáticamente. |
| No tienes API key | Usa «Obtener fotos» por si tu red no recibe 403; si falla, abre el anuncio en el navegador, copia las URLs de las imágenes y pégalas (si en el futuro se añade la opción «Pegar URLs»). |
| Quieres automatizar mucho | Valorar Apify (actor por URL) o ScraperAPI / ZenRows según coste y volumen. |

## Formato de URLs de imágenes de Idealista

Las fotos suelen seguir un patrón como:

- `https://img4.idealista.com/blur/WEB_DETAIL-XL-L/0/id.pro.es.image.master/[hash].webp`  
- O variantes con `img1`, `img2`, `img3`, dominio `.pt` o `.it` para Portugal/Italia.

En la respuesta de ZenRows, `property_images` devuelve ya la lista de URLs listas para usar.
