# Despliegue gratuito: Render + Neon

Guía paso a paso para publicar la API sin pagar nada. Tiempo estimado: 15–20 minutos.

```
GitHub ──(push)──> Render (Docker) ──> FastAPI
                        │
                        └──> Neon (PostgreSQL gestionado)
```

---

## 0. Requisitos

- Repositorio en GitHub (público o privado).
- Cuenta en [Render](https://render.com) — el plan Free no pide tarjeta.
- Cuenta en [Neon](https://neon.tech) — el plan Free no pide tarjeta.

---

## 1. Crear la base de datos en Neon

1. Entra en Neon y crea un proyecto:
   - **Region**: la más cercana a Render Fráncfort → `AWS eu-central-1` (Frankfurt).
   - **Postgres**: la versión 16 o superior.
2. En **Connection Details**, copia la cadena **directa**, no la *pooled*:

   ```
   postgresql://USER:PASSWORD@ep-xxxx.eu-central-1.aws.neon.tech/neondb?sslmode=require
   ```

   > Evita el host que contiene `-pooler`. Neon usa PgBouncer en modo
   > transacción y psycopg3 prepara sentencias por defecto; con el endpoint
   > *pooled* puedes ver `prepared statement "..." does not exist`. El endpoint
   > directo es el adecuado para una instancia pequeña como esta.

3. Convierte la URL al driver de SQLAlchemy (psycopg 3), añadiendo `+psycopg`:

   ```
   postgresql+psycopg://USER:PASSWORD@ep-xxxx.eu-central-1.aws.neon.tech/neondb?sslmode=require
   ```

4. Guarda esa URL: será el valor de `MC_DATABASE_URL`.

---

## 2. Desplegar la API en Render

1. En Render: **New → Blueprint**.
2. Conecta tu repositorio de GitHub. Render detecta `render.yaml`.
3. Revisa el servicio `montecarlo-lab-api` (runtime Docker, plan Free, health
   check `/health/ready`).
4. Cuando pida las variables, define:

   | Variable | Valor |
   |---|---|
   | `MC_DATABASE_URL` | la URL del paso 1 (secreto) |
   | `MC_ENVIRONMENT` | `production` |
   | `MC_LOG_LEVEL` | `INFO` |

5. **Apply**. Render construye la imagen y arranca el contenedor.

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

## 3. Frontend en Streamlit Community Cloud (opcional)

La app de Streamlit habla con la API desde el servidor, así que no necesita
CORS ni exponer claves en el navegador.

1. Entra en [share.streamlit.io](https://share.streamlit.io) y conecta GitHub.
2. **New app** → repositorio → *Main file path*: `frontend/app.py`.
3. En **Advanced settings → Secrets**, añade:

   ```toml
   API_BASE_URL = "https://<tu-servicio>.onrender.com"
   ```

4. Deploy. El plan gratuito requiere que el repositorio sea público.

Alternativa si el repo es privado: Hugging Face Spaces con SDK Docker, o
ejecutar el frontend en local apuntando a la API desplegada.

---

## 4. Costes y límites reales

| Recurso | Plan Free | Consecuencia práctica |
|---|---|---|
| Render Web Service | 512 MB RAM, 0.1 CPU, 750 h/mes | El servicio **se duerme a los 15 min** de inactividad; el primer request tarda ~30–60 s |
| Neon | 0,5 GB, 100 horas de cómputo/mes | La base escala a cero; el primer query tras inactividad tarda ~1 s |
| GitHub Actions | Ilimitado en repos públicos | CI sin coste |
| Streamlit Cloud | 1 GB RAM, apps públicas | Suficiente para la demo |

No hay tarjeta ni cobro mientras se respeten estos límites. Si Render marca el
servicio como *unhealthy* durante el arranque en frío, sube el timeout del
health check en el dashboard (Settings → Health Checks).

---

## 5. Problemas habituales

| Síntoma | Causa | Solución |
|---|---|---|
| `SSL connection has been closed unexpectedly` | Conexión inactiva cerrada por Neon | `pool_pre_ping=True` ya está activo; añade `?sslmode=require` y usa el endpoint directo |
| `prepared statement "_pg3_0" does not exist` | PgBouncer en modo transacción | Usa el host sin `-pooler` |
| `FATAL: password authentication failed` | Caracteres especiales sin escapar en la URL | Usa la URL que copia Neon, o codifica la contraseña |
| El deploy falla en `alembic upgrade head` | `MC_DATABASE_URL` ausente o mal formada | Revisa los logs y la variable en Render |
| Primer request tarda ~1 min | *Cold start* del plan Free | Es esperado; el health check despierta el servicio |
| 503 en `/health/ready` | La base no responde | Comprueba el proyecto de Neon y la cadena de conexión |

---

## 6. Antes de exponerlo públicamente

- Añadir autenticación (API key o JWT) y límites de uso por cliente.
- Restringir CORS al origen real del frontend si en el futuro se llama desde el navegador.
- Revisar que `MC_DATABASE_URL` esté solo en Render/Neon y nunca en el repositorio.
- Configurar alertas básicas (Render notifica caídas por email).
