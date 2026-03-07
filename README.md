# Hipochorro

Simulador y comparador de hipotecas en España. Pensado para ejecutarse en **Streamlit Community Cloud** con datos persistidos en el propio repositorio GitHub.

## Repositorio

- **GitHub:** [jarconett/hipochorro](https://github.com/jarconett/hipochorro)

## Funcionalidades

1. **Usuarios**: Creación y selección de usuario al inicio. Los datos se guardan en el repo (`data/usuarios.json`).
2. **Alta de hipotecas**: Formulario con:
   - Nombre entidad y descarga de logo por dominio (ej. `bbva.com`), guardando la imagen en `data/logos/`.
   - Nombre hipoteca, duración, cantidad solicitada, % financiación, TIN, TAE.
   - Comisión de apertura, comisión amortización parcial, mantenimiento, tasación, bonificación nómina, seguros (hogar, vida), alarma, protección de pagos, pensión, Bizum, tarjeta de crédito.
3. **Comparador**: Selección de varias hipotecas, indicación visual de la más ventajosa (TAE, % comisión de apertura, coste primer año, vinculados), campo de amortización extraordinaria anual y cuadro de amortización por años con **sistema francés**.
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

## Licencia

Uso libre con fines educativos y personales.
