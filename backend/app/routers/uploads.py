import os
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from app.core.config import settings
from app.deps import get_current_user
from app.models import models as m

router = APIRouter(prefix="/uploads", tags=["uploads"])

EXTENSIONES_COMPROBANTE = {".jpg", ".jpeg", ".png", ".pdf"}
EXTENSIONES_IMAGEN = {".jpg", ".jpeg", ".png", ".webp"}
EXTENSIONES_DOCUMENTO = {".pdf"}
TAMANO_MAXIMO_MB = 8

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR_COMPROBANTES = os.path.join(BASE_DIR, "static", "comprobantes")
DIR_LOTES = os.path.join(BASE_DIR, "static", "lotes")
DIR_MARCA = os.path.join(BASE_DIR, "static", "marca")
DIR_DOCUMENTOS_LOTE = os.path.join(BASE_DIR, "static", "documentos_lote")
os.makedirs(DIR_COMPROBANTES, exist_ok=True)
os.makedirs(DIR_LOTES, exist_ok=True)
os.makedirs(DIR_MARCA, exist_ok=True)
os.makedirs(DIR_DOCUMENTOS_LOTE, exist_ok=True)


async def _guardar_archivo(archivo: UploadFile, extensiones_permitidas: set[str], carpeta: str, subcarpeta: str) -> str:
    extension = os.path.splitext(archivo.filename or "")[1].lower()
    if extension not in extensiones_permitidas:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Formato no permitido")

    contenido = await archivo.read()
    if len(contenido) > TAMANO_MAXIMO_MB * 1024 * 1024:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"El archivo supera los {TAMANO_MAXIMO_MB}MB")

    nombre_unico = f"{uuid.uuid4().hex}{extension}"
    ruta_completa = os.path.join(carpeta, nombre_unico)
    with open(ruta_completa, "wb") as f:
        f.write(contenido)

    ruta_relativa = f"/static/{subcarpeta}/{nombre_unico}"
    if settings.PUBLIC_URL_BASE:
        return f"{settings.PUBLIC_URL_BASE}{ruta_relativa}"
    return ruta_relativa


@router.post("/comprobante")
async def subir_comprobante(
    archivo: UploadFile = File(...),
    usuario: m.Usuario = Depends(get_current_user),
):
    url = await _guardar_archivo(archivo, EXTENSIONES_COMPROBANTE, DIR_COMPROBANTES, "comprobantes")
    return {"url": url}


@router.post("/imagen-lote")
async def subir_imagen_lote(
    archivo: UploadFile = File(...),
    usuario: m.Usuario = Depends(get_current_user),
):
    url = await _guardar_archivo(archivo, EXTENSIONES_IMAGEN, DIR_LOTES, "lotes")
    return {"url": url}


@router.post("/documento-lote")
async def subir_documento_lote(
    archivo: UploadFile = File(...),
    usuario: m.Usuario = Depends(get_current_user),
):
    """PDF de partida registral u otro documento legal del lote."""
    url = await _guardar_archivo(archivo, EXTENSIONES_DOCUMENTO, DIR_DOCUMENTOS_LOTE, "documentos_lote")
    return {"url": url}


@router.post("/imagen-marca")
async def subir_imagen_marca(
    archivo: UploadFile = File(...),
    usuario: m.Usuario = Depends(get_current_user),
):
    """Logo, mascota o imagen de hero de esta instancia (una por tenant).
    Requiere sesión de admin del propio tenant — el panel superadmin la
    obtiene logueándose con las credenciales generadas al provisionar."""
    url = await _guardar_archivo(archivo, EXTENSIONES_IMAGEN, DIR_MARCA, "marca")
    return {"url": url}