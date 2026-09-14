from datetime import date, datetime
from decimal import Decimal
from typing import Optional, Any

from pydantic import BaseModel, ConfigDict, EmailStr

from app.models.models import (
    EstadoLoteEnum, FormaPagoEnum, EstadoContratoEnum, RolClienteContratoEnum,
    EstadoCuotaEnum, TipoDocumentoEnum, EstadoLeadEnum, OrigenLeadEnum,
)


class ORMBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------- AUTH ----

class LoginRequest(BaseModel):
    correo: EmailStr
    password: str


class ModuloOut(ORMBase):
    id: int
    clave: str
    nombre: str
    ruta: str


class RolOut(ORMBase):
    id: int
    clave: str
    nombre: str


class UsuarioMeOut(ORMBase):
    id: int
    nombre: str
    correo: EmailStr
    telefono: Optional[str] = None
    rol: RolOut
    id_empresa: Optional[int] = None
    modulos: list[ModuloOut] = []
    proyectos: list[int] = []


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    usuario: UsuarioMeOut


# ------------------------------------------------------------ EMPRESAS ----

class EmpresaOut(ORMBase):
    id: int
    razon_social: str
    ruc: Optional[str] = None
    nombre_comercial: str
    slug: str
    logo_url: Optional[str] = None
    activo: bool


# ----------------------------------------------------------- PROYECTOS ----

class ProyectoCreate(BaseModel):
    nombre: str
    slug: str
    departamento: Optional[str] = None
    provincia: Optional[str] = None
    distrito: Optional[str] = None
    descripcion: Optional[str] = None
    logo_url: Optional[str] = None
    moneda: str = "PEN"


class ProyectoOut(ORMBase):
    id: int
    id_empresa: int
    nombre: str
    slug: str
    departamento: Optional[str] = None
    provincia: Optional[str] = None
    distrito: Optional[str] = None
    descripcion: Optional[str] = None
    logo_url: Optional[str] = None
    moneda: str
    activo: bool


class EtapaCreate(BaseModel):
    id_proyecto: int
    nombre: str
    partida_registral: str
    sunarp_url: Optional[str] = None
    orden: Optional[int] = 0


class EtapaUpdate(BaseModel):
    nombre: Optional[str] = None
    partida_registral: Optional[str] = None
    sunarp_url: Optional[str] = None
    orden: Optional[int] = None


class EtapaOut(ORMBase):
    id: int
    id_proyecto: int
    nombre: str
    partida_registral: str
    sunarp_url: Optional[str] = None
    orden: int


class ManzanaCreate(BaseModel):
    id_proyecto: int
    id_etapa: int
    nombre: str


class ManzanaOut(ORMBase):
    id: int
    id_proyecto: int
    id_etapa: int
    nombre: str
    etapa: Optional[EtapaOut] = None


# --------------------------------------------------------------- LOTES ----

class LoteImagenOut(ORMBase):
    id: int
    url: str
    orden: int
    es_portada: bool


class LoteImagenCreate(BaseModel):
    url: str
    es_portada: bool = False
    orden: int = 0

class LoteCreate(BaseModel):
    id_proyecto: int
    id_manzana: int
    codigo: str
    ubicacion_lote: Optional[str] = None
    perimetro: Optional[Decimal] = None
    area_m2: Decimal
    precio_m2_base: Optional[Decimal] = None
    precio_total_base: Optional[Decimal] = None
    precio_m2_contado: Optional[Decimal] = None
    precio_total_contado: Optional[Decimal] = None
    inicial_financiado: Optional[Decimal] = None
    monto_financiado: Optional[Decimal] = None
    precio_total_financiado: Optional[Decimal] = None
    partida_registral: Optional[str] = None
    sunarp_url: Optional[str] = None
    orden: Optional[int] = None


class LoteUpdate(BaseModel):
    ubicacion_lote: Optional[str] = None
    mapa_x: Optional[Decimal] = None
    mapa_y: Optional[Decimal] = None
    perimetro: Optional[Decimal] = None
    area_m2: Optional[Decimal] = None
    precio_m2_base: Optional[Decimal] = None
    precio_total_base: Optional[Decimal] = None
    precio_m2_contado: Optional[Decimal] = None
    precio_total_contado: Optional[Decimal] = None
    inicial_financiado: Optional[Decimal] = None
    monto_financiado: Optional[Decimal] = None
    precio_total_financiado: Optional[Decimal] = None
    partida_registral: Optional[str] = None
    sunarp_url: Optional[str] = None
    orden: Optional[int] = None
    activo: Optional[bool] = None


class LoteEstadoUpdate(BaseModel):
    estado: EstadoLoteEnum
    observacion: Optional[str] = None


class LoteOut(ORMBase):
    id: int
    id_proyecto: int
    id_manzana: int
    codigo: str
    ubicacion_lote: Optional[str] = None
    mapa_x: Optional[Decimal] = None
    mapa_y: Optional[Decimal] = None
    perimetro: Optional[Decimal] = None
    area_m2: Decimal
    precio_m2_base: Optional[Decimal] = None
    precio_total_base: Optional[Decimal] = None
    precio_m2_contado: Optional[Decimal] = None
    precio_total_contado: Optional[Decimal] = None
    inicial_financiado: Optional[Decimal] = None
    monto_financiado: Optional[Decimal] = None
    precio_total_financiado: Optional[Decimal] = None
    estado: EstadoLoteEnum
    partida_registral: Optional[str] = None
    sunarp_url: Optional[str] = None
    activo: bool
    imagenes: list[LoteImagenOut] = []


class LotePublicoOut(ORMBase):
    """Lo que se muestra en el sitio público - sin datos sensibles."""
    id: int
    codigo: str
    ubicacion_lote: Optional[str] = None
    mapa_x: Optional[Decimal] = None
    mapa_y: Optional[Decimal] = None
    area_m2: Decimal
    precio_total_base: Optional[Decimal] = None
    precio_total_contado: Optional[Decimal] = None
    precio_total_financiado: Optional[Decimal] = None
    estado: EstadoLoteEnum
    imagenes: list[LoteImagenOut] = []


# ------------------------------------------------------------- CLIENTES ---

class ClienteCreate(BaseModel):
    tipo_documento: str = "DNI"
    numero_documento: str
    nombres: str
    apellidos: str
    correo: Optional[EmailStr] = None
    telefono: Optional[str] = None
    direccion: Optional[str] = None


class ClienteOut(ORMBase):
    id: int
    tipo_documento: str
    numero_documento: str
    nombres: str
    apellidos: str
    correo: Optional[str] = None
    telefono: Optional[str] = None


# ------------------------------------------------------------ CONTRATOS ---

class ContratoClienteIn(BaseModel):
    id_cliente: Optional[int] = None
    cliente_nuevo: Optional[ClienteCreate] = None
    rol: RolClienteContratoEnum = RolClienteContratoEnum.titular


class ContratoCreate(BaseModel):
    numero_contrato: str
    id_lote: int
    fecha_contrato: date
    precio_total: Decimal
    inicial_abonado: Decimal = Decimal("0")
    fecha_abono: Optional[date] = None
    tiene_interes: bool = False
    forma_pago: FormaPagoEnum
    frecuencia_cuota: str = "mensual"  # "mensual" | "anual"
    saldo_financiado: Decimal = Decimal("0")
    numero_cuotas: int = 0
    tea: Optional[Decimal] = None
    tcea: Optional[Decimal] = None
    tem: Optional[Decimal] = None
    fecha_inicio_interes: Optional[date] = None
    tipo_contrato: Optional[str] = None
    observaciones: Optional[str] = None
    clientes: list[ContratoClienteIn]


class ContratoLoteOut(ORMBase):
    id: int
    codigo: str
    ubicacion_lote: Optional[str] = None


class ContratoClienteOut(ORMBase):
    id_cliente: int
    nombres: str
    apellidos: str
    numero_documento: str
    rol: RolClienteContratoEnum


class ContratoOut(ORMBase):
    id: int
    numero_contrato: str
    id_lote: int
    id_proyecto: int
    fecha_contrato: date
    precio_total: Decimal
    inicial_abonado: Decimal
    forma_pago: FormaPagoEnum
    saldo_financiado: Decimal
    numero_cuotas: int
    tipo_contrato: Optional[str] = None
    observaciones: Optional[str] = None
    estado: EstadoContratoEnum
    frecuencia_cuota: str
    lote: Optional[ContratoLoteOut] = None
    clientes: list[ContratoClienteOut] = []

    @staticmethod
    def desde_contrato(contrato) -> "ContratoOut":
        return ContratoOut(
            id=contrato.id,
            numero_contrato=contrato.numero_contrato,
            id_lote=contrato.id_lote,
            id_proyecto=contrato.id_proyecto,
            fecha_contrato=contrato.fecha_contrato,
            precio_total=contrato.precio_total,
            inicial_abonado=contrato.inicial_abonado,
            forma_pago=contrato.forma_pago,
            saldo_financiado=contrato.saldo_financiado,
            numero_cuotas=contrato.numero_cuotas,
            tipo_contrato=contrato.tipo_contrato,
            observaciones=contrato.observaciones,
            estado=contrato.estado,
            frecuencia_cuota=contrato.frecuencia_cuota,
            lote=ContratoLoteOut(
                id=contrato.lote.id,
                codigo=contrato.lote.codigo,
                ubicacion_lote=contrato.lote.ubicacion_lote,
            ) if contrato.lote else None,
            clientes=[
                ContratoClienteOut(
                    id_cliente=cc.id_cliente,
                    nombres=cc.cliente.nombres,
                    apellidos=cc.cliente.apellidos,
                    numero_documento=cc.cliente.numero_documento,
                    rol=cc.rol,
                )
                for cc in contrato.clientes_rel
            ],
        )


class CronogramaOut(ORMBase):
    id: int
    numero_cuota: int
    fecha_pago_programada: date
    capital: Optional[Decimal] = None
    amortizacion: Optional[Decimal] = None
    interes_mensual: Optional[Decimal] = None
    interes_acumulado: Optional[Decimal] = None
    monto_cuota: Decimal
    requiere_pago: bool
    estado: EstadoCuotaEnum
    monto_pagado: Decimal
    fecha_pago_real: Optional[date] = None


class PagoCreate(BaseModel):
    id_cuota: Optional[int] = None
    monto: Decimal
    fecha_pago: date
    metodo_pago: Optional[str] = None
    numero_operacion: Optional[str] = None
    comprobante_url: str
    observacion: Optional[str] = None


class PagoOut(ORMBase):
    id: int
    id_cuota: Optional[int] = None
    id_contrato: int
    monto: Decimal
    fecha_pago: date
    metodo_pago: Optional[str] = None
    numero_operacion: Optional[str] = None
    comprobante_url: Optional[str] = None


# ----------------------------------------------------------------- LEADS --

class LeadCreatePublic(BaseModel):
    id_proyecto: int
    id_lote: Optional[int] = None
    nombre: str
    telefono: str
    correo: Optional[EmailStr] = None
    mensaje: Optional[str] = None
    origen: OrigenLeadEnum = OrigenLeadEnum.web


class LeadUpdate(BaseModel):
    estado: Optional[EstadoLeadEnum] = None
    id_ejecutivo_asignado: Optional[int] = None


class LeadOut(ORMBase):
    id: int
    id_proyecto: int
    id_lote: Optional[int] = None
    nombre: Optional[str] = None
    telefono: Optional[str] = None
    correo: Optional[str] = None
    mensaje: Optional[str] = None
    origen: OrigenLeadEnum
    estado: EstadoLeadEnum
    id_ejecutivo_asignado: Optional[int] = None
    created_at: datetime


class LeadSeguimientoCreate(BaseModel):
    nota: str


class LeadSeguimientoOut(ORMBase):
    id: int
    id_lead: int
    id_usuario: Optional[int] = None
    nota: Optional[str] = None
    created_at: datetime


# --------------------------------------------------------- NOTIFICACIONES -

class NotificacionOut(ORMBase):
    id: int
    tipo: str
    titulo: str
    mensaje: Optional[str] = None
    data: Optional[dict[str, Any]] = None
    leido: bool
    created_at: datetime



# ----------------------------------------------------------------- USUARIOS

class UsuarioCreate(BaseModel):
    nombre: str
    correo: EmailStr
    password: str
    telefono: Optional[str] = None
    id_rol: int
    id_empresa: Optional[int] = None
    proyectos: list[int] = []


class UsuarioUpdate(BaseModel):
    nombre: Optional[str] = None
    correo: Optional[EmailStr] = None
    password: Optional[str] = None
    telefono: Optional[str] = None
    id_rol: Optional[int] = None
    activo: Optional[bool] = None
    proyectos: Optional[list[int]] = None


class UsuarioOut(ORMBase):
    id: int
    nombre: str
    correo: EmailStr
    telefono: Optional[str] = None
    id_rol: int
    rol: RolOut
    id_empresa: Optional[int] = None
    activo: bool
    created_at: datetime
    proyectos: list[int] = []

    @staticmethod
    def desde_usuario(usuario) -> "UsuarioOut":
        return UsuarioOut(
            id=usuario.id,
            nombre=usuario.nombre,
            correo=usuario.correo,
            telefono=usuario.telefono,
            id_rol=usuario.id_rol,
            rol=RolOut.model_validate(usuario.rol),
            id_empresa=usuario.id_empresa,
            activo=usuario.activo,
            created_at=usuario.created_at,
            proyectos=[p.id for p in usuario.proyectos],
        )