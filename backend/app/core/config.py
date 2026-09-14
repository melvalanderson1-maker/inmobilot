from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    APP_NAME: str = "Inmobilot API"
    ENV: str = "development"

    DATABASE_URL: str = "postgresql+psycopg2://postgres:postgres@localhost:5432/inmobilot"

    SECRET_KEY: str = "CHANGE_ME_SUPER_SECRET"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 12  # 12 horas

    CORS_ORIGINS: str = "http://localhost:4200"

    # ---- Identidad de la inmobiliaria (una instancia = un cliente) ----
    EMPRESA_NOMBRE: str = "Mi Inmobiliaria"
    EMPRESA_SLUG: str = "demo"
    EMPRESA_DOMINIO: str = "localhost:4200"
    EMPRESA_LOGO_URL: str = "/static/branding/logo.png"
    EMPRESA_MASCOTA_URL: str = ""
    EMPRESA_HERO_URL: str = ""
    EMPRESA_MAPA_URL: str = ""
    EMPRESA_COLOR_PRIMARIO: str = "#1d4ed8"
    EMPRESA_COLOR_SECUNDARIO: str = "#0f172a"
    EMPRESA_WHATSAPP: str = ""
    EMPRESA_UBICACION: str = ""
    EMPRESA_CORREO_CONTACTO: str = ""

    # ---- Licenciamiento (Super Admin) ----
    LICENCIA_TENANT_ID: str = ""
    LICENCIA_TOKEN: str = ""
    LICENCIA_ENDPOINT: str = "https://admin.tudominio.com/api/tenants/estado"
    LICENCIA_VERIFICAR: bool = False  # false en desarrollo local

    BOOTSTRAP_SECRET: str = "CAMBIAR_ESTO_EN_PRODUCCION"

    # Dominio público desde el que se sirven los archivos subidos (imágenes,
    # comprobantes). El superadmin lo inyecta con el dominio real del backend
    # al provisionar. Si mañana migras a S3/Cloudinary, este valor deja de
    # usarse aquí y en su lugar _guardar_archivo() devuelve la URL del bucket
    # — nada más en el sistema necesita cambiar, porque ya todo guarda y
    # muestra URLs completas, no fragmentos reconstruidos.
    PUBLIC_URL_BASE: str = ""

    class Config:
        env_file = ".env"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()