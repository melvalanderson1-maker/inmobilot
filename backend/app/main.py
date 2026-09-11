import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.sockets import socket_app


from app.routers import auth, public, proyectos, lotes, leads, contratos, notificaciones, usuarios, uploads, config_publico, setup
app = FastAPI(title=settings.APP_NAME)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(public.router)
app.include_router(proyectos.router)
app.include_router(lotes.router)
app.include_router(leads.router)
app.include_router(contratos.router)
app.include_router(notificaciones.router)
app.include_router(usuarios.router)
app.include_router(uploads.router)
app.include_router(config_publico.router)
app.include_router(setup.router)

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

# Crear carpetas necesarias
os.makedirs(os.path.join(STATIC_DIR, "comprobantes"), exist_ok=True)
os.makedirs(os.path.join(STATIC_DIR, "lotes"), exist_ok=True)

# Archivos estáticos
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/health")
def health():
    return {"status": "ok", "app": settings.APP_NAME}


# Nexus (Socket.io) montado dentro de la misma app ASGI, en /socket.io
app.mount("/", socket_app)
