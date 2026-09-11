# Inmobilot — CRM Inmobiliario Multi-Tenant

## Backend (FastAPI + PostgreSQL)

```bash
cd backend
python -m venv venv
source venv/bin/activate        # en Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# edita .env con tu DATABASE_URL real y un SECRET_KEY fuerte

# 1. Crea la base de datos "inmobilot" en Postgres y corre el SQL de las 25 tablas
#    (el archivo .sql que ya tenías con el esquema completo).

# 2. Corre el seed inicial (crea Gruselva, Oro Verde, permisos por rol y el admin)
python -m scripts.seed_inicial

# 3. Levanta el servidor
uvicorn app.main:app --reload
```

- API: http://localhost:8000
- Docs interactivas (Swagger): http://localhost:8000/docs
- Socket.io (Nexus): ws://localhost:8000/socket.io
- Login de prueba: `admin@gruselva.com` / `Admin123!`

### Endpoints clave

- `POST /auth/login-json` — login (JSON: `{correo, password}`) → devuelve JWT + usuario + módulos
- `GET /public/proyectos/{empresaSlug}/{proyectoSlug}/lotes` — catálogo público, sin login
- `POST /public/leads` — captura de lead desde el sitio público
- `GET/POST /lotes`, `PATCH /lotes/{id}/estado` — gestión de lotes (requiere módulo `lotes`)
- `GET/POST /leads`, `POST /leads/{id}/seguimientos` — CRM (requiere módulo `leads`)
- `POST /contratos` — crea contrato, genera cronograma automático y marca el lote vendido
- `GET /contratos/{id}/cronograma`, `POST /contratos/{id}/pagos`
- `GET /notificaciones`, `PATCH /notificaciones/{id}/leido`

## Frontend (Angular 18, standalone)

```bash
cd frontend
npm install
npm start
```

- App: http://localhost:4200
- Catálogo público de ejemplo: http://localhost:4200/catalogo/gruselva/oro-verde
- Login: http://localhost:4200/login

Antes de compilar para producción, ajusta `src/environments/environment.prod.ts` con la URL real de tu API en el VPS (Coolify).

## Pendiente para la siguiente sesión

- Vistas de **Contratos**, **Pagos**, **Documentos** y **Usuarios** en el frontend
  (el backend de contratos y pagos ya está completo y listo para consumir).
- CRUD de usuarios en el backend (`POST/PATCH /usuarios`) — falta el router, el modelo y schemas ya existen.
- Job diario (cron / Coolify Scheduled Task) que recorra `cronograma_pagos` donde
  `fecha_pago_programada = hoy` y `estado = pendiente`, cree una `Notificacion` por cada una
  y emita el evento de socket `cuota:vence_hoy` (la función `notificar_cuota_vence_hoy` en
  `app/sockets.py` ya está lista para usarse desde ese script).
- Integración real de WhatsApp Business (la tabla `whatsapp_mensajes` y el router quedan por construir).
- Subida de archivos a `documentos` (hoy el modelo/schema asumen que ya tienes una URL,
  falta el endpoint de upload — a S3, R2 o al propio VPS).
