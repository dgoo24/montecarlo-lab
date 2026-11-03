# Despliegue gratuito: Render + Streamlit Community Cloud

Guía paso a paso para publicar la API y el frontend sin pagar nada. Tiempo
estimado: 15–20 minutos.

```
GitHub ──(push)──> Render (Docker) ──> FastAPI
                        │
                        └──> Render Postgres (PostgreSQL gestionado)
```

> **Demo actual:** [frontend](https://p776drtvmpekupvxkyiuww.streamlit.app/) ·
> [API](https://montecarlo-lab-api.onrender.com/docs)

---

## 0. Requisitos

- Repositorio en GitHub (público o privado).
- Cuenta en [Render](https://render.com) — el plan Free no pide tarjeta.
- Cuenta en [Streamlit Community Cloud](https://share.streamlit.io) conectada a
  GitHub (solo para el frontend).

---

## 1. Crear la base de datos en Render

1. En Render: **New → Postgres**.
2. Rellena:
   - **Name**: `montecarlo-db`
   - **Region**: `Frankfurt (EU Central)` (la misma que usará la API para poder
     usar la URL interna).
   - **PostgreSQL Version**: `16`.
   - **Plan**: `Free` (`$0 / month`, 256 MB RAM, 1 GB de almacenamiento).
3. Pulsa **Create database** y espera a que el estado pase de `Creating` a
   `Available` (suele tardar unos minutos).
4. En la sección **Connections**, copia la **Internal Database URL**:

   ```
   postgresql://USER:PASSWORD@HOST/DATABASE
   ```

   Esa URL solo es accesible desde servicios de Render en la misma región. Para
   conectarte desde tu equipo usa la **External Database URL**.

5. Convierte la URL al driver de SQLAlchemy (psycopg 3), añadiendo `+psycopg`:

   ```
   postgresql+psycopg://USER:PASSWORD@HOST/DATABASE
   ```

6. Guarda esa URL: será el valor de `MC_DATABASE_URL`.

> **Importante:** el plan Free de Render Postgres caduca **30 días después de
> crearlo**. Después hay 14 días de gracia antes de que Render lo elimine. No
> tiene backups. Para conservar los datos, actualiza la base a un plan de pago
> antes de la fecha de caducidad.

---

## 2. Desplegar la API en Render

1. En Render: **New → Blueprint**.
2. Conecta tu repositorio de GitHub. Render detecta `render.yaml`.
3. Revisa el servicio `montecarlo-lab-api` (runtime Docker, plan Free, región
   Frankfurt, health check `/health/ready`).
4. Cuando pida las variables, define:

   | Variable | Valor |
   |---|---|
   | `MC_DATABASE_URL` | la URL del paso 1, con `+psycopg` (secreto) |
   | `MC_ENVIRONMENT` | `production` |
   | `MC_LOG_LEVEL` | `INFO` |

5. **Deploy Blueprint**. Render construye la imagen y arranca el contenedor.

El `entrypoint.sh` ejecuta `alembic upgrade head` antes de lanzar uvicorn, así
que el esquema se crea en el primer arranque sin pasos manuales.

### Verificar

```bash
curl https://<tu-servicio>.onrender.com/health
curl https://<tu-servicio>.onrender.com/health/ready
# Documentación interactiva:
# https://<tu-servicio>.onrender.com/docs
```

Después de desplegar, ejecuta el smoke test contra producción:

```bash
python scripts/smoke_test.py --base-url https://<tu-servicio>.onrender.com
```

---

## 3. Frontend en Streamlit Community Cloud

La app de Streamlit habla con la API desde el servidor, así que no necesita
CORS ni expone claves en el navegador.

1. Entra en [share.streamlit.io](https://share.streamlit.io) y conecta GitHub.
2. **Create app → Deploy a public app from GitHub**.
3. Rellena:
   - **Repository**: `dgoo24/montecarlo-lab`
   - **Branch**: `main`
   - **Main file path**: `frontend/app.py`
4. En **Advanced settings**:
   - **Python version**: `3.12`
   - **Secrets**:

     ```toml
     API_BASE_URL = "https://<tu-servicio>.onrender.com"
     ```

5. **Deploy**. El plan gratuito requiere que el repositorio sea público.

Streamlit instala las dependencias de `frontend/requirements.txt` (situado junto
al entrypoint, que es una ubicación válida según la documentación de Streamlit).

Alternativa si el repo es privado: Hugging Face Spaces con SDK Docker, o
ejecutar el frontend en local apuntando a la API desplegada.

---

## 4. Costes y límites reales

| Recurso | Plan Free | Consecuencia práctica |
|---|---|---|
| Render Web Service | 512 MB RAM, 0.1 CPU, 750 h/mes | El servicio **se duerme a los 15 min** de inactividad; el primer request tarda ~30–60 s |
| Render Postgres | 256 MB RAM, 1 GB, **caduca a los 30 días** | Sin backups; hay 14 días de gracia antes del borrado. Actualiza a pago para conservarlo |
| GitHub Actions | Ilimitado en repos públicos | CI sin coste |
| Streamlit Cloud | 1 GB RAM, apps públicas | Suficiente para la demo |

No hay tarjeta ni cobro mientras se respeten estos límites. Si Render marca el
servicio como *unhealthy* durante el arranque en frío, sube el timeout del
health check en el dashboard (Settings → Health Checks).

---

## 5. Problemas habituales

| Síntoma | Causa | Solución |
|---|---|---|
| `SSL connection has been closed unexpectedly` | Conexión inactiva cerrada por el proxy de Render | `pool_pre_ping=True` ya está activo; usa la URL interna y comprueba que la base sigue `Available` |
| `FATAL: password authentication failed` | Caracteres especiales sin escapar en la URL | Copia la URL interna desde Render, o codifica la contraseña con `urllib.parse.quote` |
| El deploy falla en `alembic upgrade head` | `MC_DATABASE_URL` ausente o mal formada | Revisa los logs y la variable en Render; debe empezar por `postgresql+psycopg://` |
| Primer request tarda ~1 min | *Cold start* del plan Free | Es esperado; el health check despierta el servicio |
| 503 en `/health/ready` | La base no responde, caducó o está suspendida | Comprueba el estado de `montecarlo-db` en Render y la cadena de conexión |
| Streamlit muestra un error de conexión | Falta el secreto `API_BASE_URL` o apunta a otra URL | Edita **App settings → Secrets** y reinicia la app |
| El frontend muestra 0 en los KPIs | La base está vacía o la API no responde | Ejecuta el smoke test y recarga la app |

---

## 6. Antes de exponerlo públicamente

- Añadir autenticación (API key o JWT) y límites de uso por cliente.
- Restringir CORS al origen real del frontend si en el futuro se llama desde el navegador.
- Revisar que `MC_DATABASE_URL` esté solo en las variables de Render y nunca en el repositorio.
- Configurar alertas básicas (Render notifica caídas por email).
- Renovar o actualizar la base de datos antes de que caduque el plan Free.
