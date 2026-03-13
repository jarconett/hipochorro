# Hipochorro

Simulador y comparador de hipotecas en España. Pensado para ejecutarse en **Streamlit Community Cloud** con datos persistidos en el propio repositorio GitHub.

## Repositorio

- **GitHub:** [jarconett/hipochorro](https://github.com/jarconett/hipochorro)

## Funcionalidades

1. **Usuarios**: Creación y selección de usuario al inicio. Los datos se guardan en el repo (`data/usuarios.json`).
2. **Alta de hipotecas**: Formulario con:
   - Nombre entidad y descarga de logo por dominio (ej. `bbva.com`), guardando la imagen en `data/logos/`.
   - Nombre hipoteca, duración, cantidad solicitada, % financiación, TIN, TAE.
   - Comisión amortización parcial, mantenimiento, tasación, bonificación nómina, seguros (hogar, vida), alarma, protección de pagos, pensión, Bizum, tarjeta de crédito.
3. **Comparador**: Selección de varias hipotecas, indicación visual de la más ventajosa (TAE, coste primer año, vinculados), campo de amortización extraordinaria anual y cuadro de amortización por años con **sistema francés**.
4. **Branding**: portada con logo y favicon desde `assets/`.

## Despliegue en Streamlit Cloud

1. Conecta tu cuenta de GitHub a [Streamlit Community Cloud](https://share.streamlit.io/).
2. Despliega desde el repo `jarconett/hipochorro` (rama `main` por defecto).
3. **Secrets**: en la configuración de la app, añade un secret:
   - **Nombre:** `GITHUB_TOKEN`
   - **Valor:** un [Personal Access Token (PAT)](https://github.com/settings/tokens) de GitHub con permiso **repo** (acceso completo a repositorios privados si aplica, o al menos a este repo).

Con eso la app podrá leer y escribir en el mismo repositorio (usuarios, hipotecas y logos).

## Ejecución local

```bash
pip install -r requirements.txt
# Opcional: export GITHUB_TOKEN=tu_token para persistir en GitHub
streamlit run app.py
```

Sin `GITHUB_TOKEN` la app arranca pero no podrá guardar usuarios ni hipotecas (solo lectura si los archivos ya existen en el repo).

## Estructura de datos en el repo

- `assets/logo.png`: logo de la app (portada).
- `assets/favicon.png`: favicon de la app (icono de pestaña).
- `data/usuarios.json`: lista de usuarios (id, nombre, email).
- `data/hipotecas/usuario_{id}.json`: hipotecas por usuario.
- `data/logos/{entidad_slug}.png`: logos de entidades.
- `data/inmuebles/usuario_{id}.json`: agenda de inmuebles por usuario.
- `data/inmuebles_fotos/`: fotos de cada inmueble (subidas desde la app).
- `data/inmuebles_sunlight/`: ficheros JSON con horas de sol anuales por inmueble.

## Dependencias y código de terceros

Esta app se apoya en varias librerías y servicios externos. Todo el código específico de la lógica de negocio de hipotecas e inmuebles está desarrollado para este proyecto, pero se usan:

- **Streamlit** (`streamlit`): framework para la interfaz web.  
  - Proyecto original: https://github.com/streamlit/streamlit
- **PyGithub** (`PyGithub`): cliente de la API de GitHub para leer/escribir JSON y binarios en el propio repo.  
  - Proyecto original: https://github.com/PyGithub/PyGithub
- **Folium** (`folium`) + **streamlit-folium**: visualización de mapas interactivos en la ficha de cada inmueble.  
  - Folium: https://github.com/python-visualization/folium  
  - streamlit-folium: https://github.com/randyzwitch/streamlit-folium
- **OSRM** (servicio público `router.project-osrm.org`): cálculo de rutas en coche y tiempos a la ciudad de destino.  
  - Proyecto original: http://project-osrm.org/
- **Nominatim (OpenStreetMap)**: geocodificación de direcciones (localización de inmuebles).  
  - Política de uso: https://operations.osmfoundation.org/policies/nominatim/
- **Apify** (`apify-client`): cliente para consumir el actor público **Idealista Property Listing Scraper** cuando se intenta obtener imágenes de anuncios de Idealista.  
  - Cliente: https://github.com/apify/apify-client-python  
  - Actor usado: `duncan01/idealista-property-listing-scraper` en la plataforma Apify (sujeto a sus términos de uso).
- **BeautifulSoup4** (`beautifulsoup4`): parseo de HTML como alternativa cuando no se usa Apify para extraer URLs de imágenes.

El uso de estos proyectos se realiza respetando sus licencias y términos de servicio. Esta app **no** redistribuye su código fuente; solo los consume como dependencias desde `requirements.txt`. Cualquier uso del proyecto debe tener en cuenta también las licencias y condiciones de esos proyectos externos.

## Licencia

Uso libre con fines educativos y personales.
