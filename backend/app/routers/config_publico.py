from fastapi import APIRouter

from app.core.config import settings

router = APIRouter(prefix="/config", tags=["config"])


@router.get("/tenant")
def obtener_config_tenant():
    """
    Expone la identidad de marca de esta instancia (una inmobiliaria por deploy).
    El frontend consume esto UNA vez al cargar la app, y con eso pinta
    logo, nombre, colores y datos de contacto — sin nada hardcodeado.
    """
    return {
        "nombre": settings.EMPRESA_NOMBRE,
        "slug": settings.EMPRESA_SLUG,
        "logo_url": settings.EMPRESA_LOGO_URL,
        "mascota_url": settings.EMPRESA_MASCOTA_URL,
        "hero_url": settings.EMPRESA_HERO_URL,
        "color_primario": settings.EMPRESA_COLOR_PRIMARIO,
        "color_secundario": settings.EMPRESA_COLOR_SECUNDARIO,
        "whatsapp": settings.EMPRESA_WHATSAPP,
        "ubicacion": settings.EMPRESA_UBICACION,
        "correo_contacto": settings.EMPRESA_CORREO_CONTACTO,
    }