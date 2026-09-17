import enum

from sqlalchemy import (
    Column, Integer, BigInteger, String, Boolean, Numeric, Text, Date,
    DateTime, ForeignKey, UniqueConstraint, Index, Enum as SAEnum
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base


# =========================================================================
# ENUMS (deben coincidir con los CREATE TYPE del SQL)
# =========================================================================

class EstadoLoteEnum(str, enum.Enum):
    libre = "libre"
    vendido = "vendido"
    bloqueado = "bloqueado"
    separado = "separado"


class FormaPagoEnum(str, enum.Enum):
    contado = "contado"
    credito = "credito"


class EstadoContratoEnum(str, enum.Enum):
    vigente = "vigente"
    cancelado = "cancelado"
    moroso = "moroso"
    anulado = "anulado"


class RolClienteContratoEnum(str, enum.Enum):
    titular = "titular"
    conyuge = "conyuge"
    copropietario = "copropietario"


class EstadoCuotaEnum(str, enum.Enum):
    pendiente = "pendiente"
    pagada = "pagada"
    vencida = "vencida"
    parcial = "parcial"


class TipoDocumentoEnum(str, enum.Enum):
    minuta = "minuta"
    certificado = "certificado"
    comprobante_pago = "comprobante_pago"
    dni = "dni"
    contrato_firmado = "contrato_firmado"
    otro = "otro"


class EstadoLeadEnum(str, enum.Enum):
    nuevo = "nuevo"
    contactado = "contactado"
    en_seguimiento = "en_seguimiento"
    convertido = "convertido"
    descartado = "descartado"


class OrigenLeadEnum(str, enum.Enum):
    web = "web"
    whatsapp = "whatsapp"
    facebook = "facebook"
    instagram = "instagram"
    referido = "referido"
    otro = "otro"


# =========================================================================
# 1. TENANT / SAAS
# =========================================================================

class Plan(Base):
    __tablename__ = "planes"

    id = Column(Integer, primary_key=True)
    nombre = Column(String(50), nullable=False)
    max_proyectos = Column(Integer)
    max_usuarios = Column(Integer)
    precio_mensual = Column(Numeric(10, 2))
    activo = Column(Boolean, nullable=False, default=True)

    empresas = relationship("Empresa", back_populates="plan")


class Empresa(Base):
    __tablename__ = "empresas"

    id = Column(Integer, primary_key=True)
    razon_social = Column(String(200), nullable=False)
    ruc = Column(String(20))
    nombre_comercial = Column(String(150), nullable=False)
    slug = Column(String(100), nullable=False, unique=True)
    logo_url = Column(String(300))
    dominio_personalizado = Column(String(150))
    id_plan = Column(Integer, ForeignKey("planes.id"))
    activo = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    plan = relationship("Plan", back_populates="empresas")
    proyectos = relationship("Proyecto", back_populates="empresa")
    usuarios = relationship("Usuario", back_populates="empresa")


# =========================================================================
# 2. ROLES, MÓDULOS Y PERMISOS
# =========================================================================

class Rol(Base):
    __tablename__ = "roles"

    id = Column(Integer, primary_key=True)
    id_empresa = Column(Integer, ForeignKey("empresas.id", ondelete="CASCADE"), nullable=True)
    clave = Column(String(50), nullable=False)
    nombre = Column(String(100), nullable=False)
    descripcion = Column(String(255))

    __table_args__ = (UniqueConstraint("id_empresa", "clave", name="uq_rol_empresa_clave"),)

    modulos = relationship("Modulo", secondary="rol_modulo", back_populates="roles")
    usuarios = relationship("Usuario", back_populates="rol")


class Modulo(Base):
    __tablename__ = "modulos"

    id = Column(Integer, primary_key=True)
    clave = Column(String(50), nullable=False, unique=True)
    nombre = Column(String(100), nullable=False)
    ruta = Column(String(200), nullable=False)
    listo = Column(Boolean, nullable=False, default=False)

    roles = relationship("Rol", secondary="rol_modulo", back_populates="modulos")


class RolModulo(Base):
    __tablename__ = "rol_modulo"

    id_rol = Column(Integer, ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True)
    id_modulo = Column(Integer, ForeignKey("modulos.id", ondelete="CASCADE"), primary_key=True)


class Usuario(Base):
    __tablename__ = "usuarios"

    id = Column(Integer, primary_key=True)
    nombre = Column(String(150), nullable=False)
    correo = Column(String(200), nullable=False, unique=True)
    password_hash = Column(String(255), nullable=False)
    telefono = Column(String(20))
    whatsapp_id = Column(String(50))
    id_rol = Column(Integer, ForeignKey("roles.id"), nullable=False)
    id_empresa = Column(Integer, ForeignKey("empresas.id", ondelete="CASCADE"))
    activo = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    rol = relationship("Rol", back_populates="usuarios")
    empresa = relationship("Empresa", back_populates="usuarios")
    proyectos = relationship("Proyecto", secondary="usuario_proyecto", back_populates="usuarios")


class UsuarioEmpresa(Base):
    __tablename__ = "usuario_empresa"

    id_usuario = Column(Integer, ForeignKey("usuarios.id", ondelete="CASCADE"), primary_key=True)
    id_empresa = Column(Integer, ForeignKey("empresas.id", ondelete="CASCADE"), primary_key=True)


class UsuarioModuloPermiso(Base):
    __tablename__ = "usuario_modulo_permiso"

    id_usuario = Column(Integer, ForeignKey("usuarios.id", ondelete="CASCADE"), primary_key=True)
    id_modulo = Column(Integer, ForeignKey("modulos.id", ondelete="CASCADE"), primary_key=True)
    habilitado = Column(Boolean, default=True)


# =========================================================================
# 3. PROYECTOS
# =========================================================================

class Proyecto(Base):
    __tablename__ = "proyectos"

    id = Column(Integer, primary_key=True)
    id_empresa = Column(Integer, ForeignKey("empresas.id", ondelete="CASCADE"), nullable=False)
    nombre = Column(String(150), nullable=False)
    slug = Column(String(100), nullable=False)
    departamento = Column(String(100))
    provincia = Column(String(100))
    distrito = Column(String(100))
    descripcion = Column(Text)
    logo_url = Column(String(300))
    moneda = Column(String(10), default="PEN")
    activo = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (UniqueConstraint("id_empresa", "slug", name="uq_proyecto_empresa_slug"),)

    empresa = relationship("Empresa", back_populates="proyectos")
    etapas = relationship("Etapa", back_populates="proyecto")
    manzanas = relationship("Manzana", back_populates="proyecto")
    usuarios = relationship("Usuario", secondary="usuario_proyecto", back_populates="proyectos")



class Etapa(Base):
    __tablename__ = "etapas"

    id = Column(Integer, primary_key=True)
    id_proyecto = Column(Integer, ForeignKey("proyectos.id", ondelete="CASCADE"), nullable=False)
    nombre = Column(String(100), nullable=False)
    partida_registral = Column(String(50), nullable=False)
    sunarp_url = Column(String(300))
    orden = Column(Integer, default=0)
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("id_proyecto", "partida_registral", name="uq_etapa_proyecto_partida"),
    )

    proyecto = relationship("Proyecto", back_populates="etapas")
    manzanas = relationship("Manzana", back_populates="etapa")


class UsuarioProyecto(Base):
    __tablename__ = "usuario_proyecto"

    id_usuario = Column(Integer, ForeignKey("usuarios.id", ondelete="CASCADE"), primary_key=True)
    id_proyecto = Column(Integer, ForeignKey("proyectos.id", ondelete="CASCADE"), primary_key=True)


class Manzana(Base):
    __tablename__ = "manzanas"

    id = Column(Integer, primary_key=True)
    id_proyecto = Column(Integer, ForeignKey("proyectos.id", ondelete="CASCADE"), nullable=False)
    id_etapa = Column(Integer, ForeignKey("etapas.id", ondelete="CASCADE"), nullable=False)
    nombre = Column(String(20), nullable=False)

    __table_args__ = (
        UniqueConstraint("id_etapa", "nombre", name="uq_manzana_etapa_nombre"),
    )

    proyecto = relationship("Proyecto", back_populates="manzanas")
    etapa = relationship("Etapa", back_populates="manzanas")
    lotes = relationship("Lote", back_populates="manzana")

# =========================================================================
# 4. LOTES
# =========================================================================

class Lote(Base):
    __tablename__ = "lotes"

    id = Column(Integer, primary_key=True)
    id_proyecto = Column(Integer, ForeignKey("proyectos.id", ondelete="CASCADE"), nullable=False)
    id_manzana = Column(Integer, ForeignKey("manzanas.id", ondelete="CASCADE"), nullable=False)
    codigo = Column(String(20), nullable=False)
    ubicacion_lote = Column(String(50))
    perimetro = Column(Numeric(10, 2))
    area_m2 = Column(Numeric(10, 2), nullable=False)
    precio_m2_base = Column(Numeric(10, 2))
    precio_total_base = Column(Numeric(12, 2))
    precio_m2_contado = Column(Numeric(10, 2))
    precio_total_contado = Column(Numeric(12, 2))
    precio_m2_financiado = Column(Numeric(10, 2))
    inicial_financiado = Column(Numeric(12, 2))
    monto_financiado = Column(Numeric(12, 2))
    precio_total_financiado = Column(Numeric(12, 2))
    inicial_financiado_60c = Column(Numeric(12, 2))
    cuota_mensual_60c = Column(Numeric(10, 2))
    frontis = Column(String(50))
    estado = Column(SAEnum(EstadoLoteEnum, name="estado_lote_enum"), nullable=False, default=EstadoLoteEnum.libre)
    partida_registral = Column(String(50))
    sunarp_url = Column(String(300))
    orden = Column(Integer)
    mapa_x = Column(Numeric(5, 2))  # posición % horizontal sobre la maqueta
    mapa_y = Column(Numeric(5, 2))  # posición % vertical sobre la maqueta
    activo = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("id_proyecto", "codigo", name="uq_lote_proyecto_codigo"),
        Index("idx_lotes_estado", "id_proyecto", "estado"),
    )

    creado_por = Column(Integer, ForeignKey("usuarios.id"))
    actualizado_por = Column(Integer, ForeignKey("usuarios.id"))
    servicios = Column(JSONB, nullable=True)

    manzana = relationship("Manzana", back_populates="lotes")
    imagenes = relationship("LoteImagen", back_populates="lote")
    usuario_creador = relationship("Usuario", foreign_keys=[creado_por])
    usuario_actualizador = relationship("Usuario", foreign_keys=[actualizado_por])


class LoteImagen(Base):
    __tablename__ = "lote_imagenes"

    id = Column(Integer, primary_key=True)
    id_lote = Column(Integer, ForeignKey("lotes.id", ondelete="CASCADE"), nullable=False)
    url = Column(String(300), nullable=False)
    orden = Column(Integer, default=0)
    es_portada = Column(Boolean, default=False)

    lote = relationship("Lote", back_populates="imagenes")


class LoteEstadoHistorial(Base):
    __tablename__ = "lote_estado_historial"

    id = Column(BigInteger, primary_key=True)
    id_lote = Column(Integer, ForeignKey("lotes.id", ondelete="CASCADE"), nullable=False)
    estado_anterior = Column(SAEnum(EstadoLoteEnum, name="estado_lote_enum"))
    estado_nuevo = Column(SAEnum(EstadoLoteEnum, name="estado_lote_enum"), nullable=False)
    id_usuario = Column(Integer, ForeignKey("usuarios.id"))
    observacion = Column(String(300))
    created_at = Column(DateTime, server_default=func.now())


# =========================================================================
# 5. CLIENTES Y CONTRATOS
# =========================================================================

class Cliente(Base):
    __tablename__ = "clientes"

    id = Column(Integer, primary_key=True)
    id_empresa = Column(Integer, ForeignKey("empresas.id", ondelete="CASCADE"), nullable=False)
    tipo_documento = Column(String(10), default="DNI")
    numero_documento = Column(String(20), nullable=False)
    nombres = Column(String(150), nullable=False)
    apellidos = Column(String(150), nullable=False)
    correo = Column(String(200))
    telefono = Column(String(20))
    direccion = Column(String(250))
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (UniqueConstraint("id_empresa", "numero_documento", name="uq_cliente_empresa_doc"),)


class Contrato(Base):
    __tablename__ = "contratos"

    id = Column(Integer, primary_key=True)
    numero_contrato = Column(String(30), nullable=False)
    id_lote = Column(Integer, ForeignKey("lotes.id"), nullable=False)
    id_proyecto = Column(Integer, ForeignKey("proyectos.id"), nullable=False)
    id_empresa = Column(Integer, ForeignKey("empresas.id"), nullable=False)
    fecha_contrato = Column(Date, nullable=False)
    precio_total = Column(Numeric(12, 2), nullable=False)
    inicial_abonado = Column(Numeric(12, 2), default=0)
    fecha_abono = Column(Date)
    tiene_interes = Column(Boolean, default=False)
    forma_pago = Column(SAEnum(FormaPagoEnum, name="forma_pago_enum"), nullable=False)
    saldo_financiado = Column(Numeric(12, 2), default=0)
    numero_cuotas = Column(Integer, default=0)
    tea = Column(Numeric(6, 3))
    tcea = Column(Numeric(6, 3))
    tem = Column(Numeric(6, 3))
    fecha_inicio_interes = Column(Date)
    tipo_contrato = Column(String(100))
    observaciones = Column(String(300))
    frecuencia_cuota = Column(String(10), nullable=False, default="mensual")
    estado = Column(SAEnum(EstadoContratoEnum, name="estado_contrato_enum"), nullable=False, default=EstadoContratoEnum.vigente)
    sistema_contable_status = Column(String(20))
    id_usuario_registro = Column(Integer, ForeignKey("usuarios.id"))
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("id_empresa", "numero_contrato", name="uq_contrato_empresa_numero"),
        Index("idx_contratos_lote", "id_lote"),
    )

    cronograma = relationship("CronogramaPago", back_populates="contrato")
    clientes_rel = relationship("ContratoCliente", back_populates="contrato")
    lote = relationship("Lote")


class ContratoCliente(Base):
    __tablename__ = "contrato_clientes"

    id_contrato = Column(Integer, ForeignKey("contratos.id", ondelete="CASCADE"), primary_key=True)
    id_cliente = Column(Integer, ForeignKey("clientes.id", ondelete="CASCADE"), primary_key=True)
    rol = Column(SAEnum(RolClienteContratoEnum, name="rol_cliente_contrato_enum"), nullable=False, default=RolClienteContratoEnum.titular)

    contrato = relationship("Contrato", back_populates="clientes_rel")
    cliente = relationship("Cliente")


# =========================================================================
# 6. CRONOGRAMA DE PAGOS Y PAGOS
# =========================================================================

class CronogramaPago(Base):
    __tablename__ = "cronograma_pagos"

    id = Column(BigInteger, primary_key=True)
    id_contrato = Column(Integer, ForeignKey("contratos.id", ondelete="CASCADE"), nullable=False)
    numero_cuota = Column(Integer, nullable=False)
    fecha_pago_programada = Column(Date, nullable=False)
    capital = Column(Numeric(12, 2))
    amortizacion = Column(Numeric(12, 2))
    interes_mensual = Column(Numeric(12, 2))
    interes_acumulado = Column(Numeric(12, 2))
    monto_cuota = Column(Numeric(12, 2), nullable=False)
    requiere_pago = Column(Boolean, nullable=False, default=True)
    estado = Column(SAEnum(EstadoCuotaEnum, name="estado_cuota_enum"), nullable=False, default=EstadoCuotaEnum.pendiente)
    monto_pagado = Column(Numeric(12, 2), default=0)
    fecha_pago_real = Column(Date)
    observacion = Column(String(300))

    __table_args__ = (
        UniqueConstraint("id_contrato", "numero_cuota", name="uq_cronograma_contrato_cuota"),
        Index("idx_cronograma_fecha_estado", "fecha_pago_programada", "estado"),
    )

    contrato = relationship("Contrato", back_populates="cronograma")


class Pago(Base):
    __tablename__ = "pagos"

    id = Column(BigInteger, primary_key=True)
    id_cuota = Column(BigInteger, ForeignKey("cronograma_pagos.id"))
    id_contrato = Column(Integer, ForeignKey("contratos.id"), nullable=False)
    monto = Column(Numeric(12, 2), nullable=False)
    fecha_pago = Column(Date, nullable=False)
    metodo_pago = Column(String(50))
    numero_operacion = Column(String(50))
    comprobante_url = Column(String(300))
    registrado_por = Column(Integer, ForeignKey("usuarios.id"))
    observacion = Column(String(300))
    created_at = Column(DateTime, server_default=func.now())


# =========================================================================
# 7. DOCUMENTOS
# =========================================================================

class Documento(Base):
    __tablename__ = "documentos"

    id = Column(BigInteger, primary_key=True)
    id_contrato = Column(Integer, ForeignKey("contratos.id", ondelete="CASCADE"))
    id_cliente = Column(Integer, ForeignKey("clientes.id", ondelete="CASCADE"))
    tipo_documento = Column(SAEnum(TipoDocumentoEnum, name="tipo_documento_enum"), nullable=False)
    nombre_archivo = Column(String(200))
    url_archivo = Column(String(300), nullable=False)
    es_publico = Column(Boolean, nullable=False, default=False)
    subido_por = Column(Integer, ForeignKey("usuarios.id"))
    created_at = Column(DateTime, server_default=func.now())


# =========================================================================
# 8. CRM: LEADS Y SEGUIMIENTO
# =========================================================================

class Lead(Base):
    __tablename__ = "leads"

    id = Column(BigInteger, primary_key=True)
    id_empresa = Column(Integer, ForeignKey("empresas.id"), nullable=False)
    id_proyecto = Column(Integer, ForeignKey("proyectos.id"), nullable=False)
    id_lote = Column(Integer, ForeignKey("lotes.id"))
    nombre = Column(String(150))
    telefono = Column(String(20))
    correo = Column(String(200))
    mensaje = Column(String(500))
    origen = Column(SAEnum(OrigenLeadEnum, name="origen_lead_enum"), default=OrigenLeadEnum.web)
    estado = Column(SAEnum(EstadoLeadEnum, name="estado_lead_enum"), nullable=False, default=EstadoLeadEnum.nuevo)
    id_ejecutivo_asignado = Column(Integer, ForeignKey("usuarios.id"))
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (Index("idx_leads_estado", "id_proyecto", "estado"),)

    seguimientos = relationship("LeadSeguimiento", back_populates="lead")


class LeadSeguimiento(Base):
    __tablename__ = "lead_seguimientos"

    id = Column(BigInteger, primary_key=True)
    id_lead = Column(BigInteger, ForeignKey("leads.id", ondelete="CASCADE"), nullable=False)
    id_usuario = Column(Integer, ForeignKey("usuarios.id"))
    nota = Column(String(500))
    created_at = Column(DateTime, server_default=func.now())

    lead = relationship("Lead", back_populates="seguimientos")


# =========================================================================
# 9. WHATSAPP BUSINESS
# =========================================================================

class WhatsappMensaje(Base):
    __tablename__ = "whatsapp_mensajes"

    id = Column(BigInteger, primary_key=True)
    id_lead = Column(BigInteger, ForeignKey("leads.id", ondelete="SET NULL"))
    id_cliente = Column(Integer, ForeignKey("clientes.id", ondelete="SET NULL"))
    numero_telefono = Column(String(20), nullable=False)
    direccion = Column(String(10), nullable=False)
    mensaje = Column(Text)
    tipo_mensaje = Column(String(20), default="texto")
    estado_envio = Column(String(20))
    wa_message_id = Column(String(100))
    created_at = Column(DateTime, server_default=func.now())


# =========================================================================
# 10. NOTIFICACIONES
# =========================================================================

class Notificacion(Base):
    __tablename__ = "notificaciones"

    id = Column(BigInteger, primary_key=True)
    id_empresa = Column(Integer, ForeignKey("empresas.id"))
    id_usuario_destino = Column(Integer, ForeignKey("usuarios.id"))
    tipo = Column(String(50), nullable=False)
    titulo = Column(String(150), nullable=False)
    mensaje = Column(String(300))
    data = Column(JSONB)
    leido = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (Index("idx_notif_usuario_leido", "id_usuario_destino", "leido"),)


# =========================================================================
# 11. METAS DE VENTAS
# =========================================================================

class MetaVenta(Base):
    __tablename__ = "metas_ventas"

    id = Column(Integer, primary_key=True)
    id_usuario = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    id_proyecto = Column(Integer, ForeignKey("proyectos.id"), nullable=False)
    periodo = Column(String(7), nullable=False)
    meta_lotes = Column(Integer)
    meta_monto = Column(Numeric(12, 2))

    __table_args__ = (UniqueConstraint("id_usuario", "id_proyecto", "periodo", name="uq_meta_usuario_proyecto_periodo"),)
