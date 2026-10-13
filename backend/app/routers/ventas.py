from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload, selectinload

from app.core.database import get_db
from app.deps import require_permiso
from app.models import models as m
from app.schemas import schemas as s
from app.services import venta_service as svc
import logging

from sqlalchemy.orm import joinedload
from app.services import separacion_service as sep_svc
from app.sockets import notificar_venta, notificar_cambio_estado_lote, notificar_nuevo_contrato

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/ventas", tags=["ventas"])


def _resumen_socket(venta: m.Venta) -> dict:
    return {"id": venta.id, "id_lote": venta.id_lote, "estado": venta.estado.value}


async def _emitir_contrato_creado(db: Session, id_contrato: int, venta: m.Venta, usuario: m.Usuario):
    """Tiempo real: venta nueva + contrato nuevo (lista de Contratos) + lote vendido.
    Si el aviso falla, NO debe romper la operación: los datos ya están guardados."""
    try:
        contrato = (
            db.query(m.Contrato)
            .options(
                joinedload(m.Contrato.lote),
                joinedload(m.Contrato.clientes_rel).joinedload(m.ContratoCliente.cliente),
            )
            .filter(m.Contrato.id == id_contrato)
            .first()
        )
        await notificar_venta("venta:nueva", _resumen_socket(venta), id_proyecto=venta.id_proyecto)
        await notificar_nuevo_contrato(
            s.ContratoOut.desde_contrato(contrato).model_dump(mode="json"),
            id_proyecto=venta.id_proyecto, id_empresa=usuario.id_empresa,
        )
        await notificar_cambio_estado_lote(
            sep_svc.lote_out_dict(db, venta.id_lote),
            id_proyecto=venta.id_proyecto, id_empresa=usuario.id_empresa,
        )
    except Exception:
        logger.exception("No se pudo emitir el aviso en tiempo real del contrato %s", id_contrato)

@router.post("/desde-separacion/{id_separacion}", response_model=s.VentaOut, status_code=status.HTTP_201_CREATED)
async def crear_venta_desde_separacion(
    id_separacion: int,
    payload: s.VentaCreate,
    usuario: m.Usuario = Depends(require_permiso("crear_venta")),
    db: Session = Depends(get_db),
):
    sep = db.query(m.Separacion).filter(
        m.Separacion.id == id_separacion, m.Separacion.id_empresa == usuario.id_empresa
    ).first()
    if not sep:
        raise HTTPException(status_code=404, detail="Separación no encontrada")
    if sep.estado != m.EstadoSeparacionEnum.convertida:
        raise HTTPException(status_code=409, detail="La separación debe estar convertida antes de iniciar la venta")

    existente = db.query(m.Venta).filter(m.Venta.id_separacion == id_separacion).first()
    if existente:
        raise HTTPException(status_code=409, detail="Esta separación ya tiene una venta iniciada")
    if payload.forma_pago == m.FormaPagoEnum.credito:
        if not payload.datos_credito:
            raise HTTPException(status_code=422, detail="Completa los datos del crédito (inicial, fecha, operación y plazo)")
        if payload.datos_credito.frecuencia_cuota not in ("mensual", "semestral", "unico"):
            raise HTTPException(status_code=422, detail="La frecuencia debe ser mensual, semestral o pago único")
        if not (1 <= payload.datos_credito.plazo_anios <= 2):
            raise HTTPException(status_code=422, detail="El plazo máximo es de 2 años; si es mayor requiere autorización")
    if len(payload.clientes) > 4:
        raise HTTPException(status_code=422, detail="Una venta admite como máximo 4 compradores")
    ids_compradores = [i.id_cliente for i in payload.clientes if i.id_cliente]
    if len(ids_compradores) != len(set(ids_compradores)):
        raise HTTPException(status_code=422, detail="Un mismo cliente no puede figurar dos veces como comprador")

    venta = m.Venta(
        id_empresa=usuario.id_empresa,
        id_proyecto=sep.id_proyecto,
        id_lote=sep.id_lote,
        id_separacion=sep.id,
        forma_pago=payload.forma_pago,
        precio_total=payload.precio_total,
        id_usuario_registro=usuario.id,
        pagos_previos=[p.model_dump(mode="json") for p in payload.pagos_previos] if payload.pagos_previos else None,
        datos_credito=payload.datos_credito.model_dump(mode="json") if payload.datos_credito else None,
    )
    db.add(venta)
    db.flush()

    for item in payload.clientes or [s.VentaClienteIn(id_cliente=sep.id_cliente)]:
        if item.id_cliente:
            cliente = db.query(m.Cliente).filter(
                m.Cliente.id == item.id_cliente, m.Cliente.id_empresa == usuario.id_empresa
            ).first()
            if not cliente:
                raise HTTPException(status_code=404, detail=f"Cliente {item.id_cliente} no encontrado")
        elif item.cliente_nuevo:
            cliente = m.Cliente(id_empresa=usuario.id_empresa, **item.cliente_nuevo.model_dump(exclude={"conyuge"}))
            db.add(cliente)
            db.flush()
        else:
            raise HTTPException(status_code=422, detail="Cada comprador requiere id_cliente o cliente_nuevo")
        db.add(m.VentaCliente(id_venta=venta.id, id_cliente=cliente.id, rol=item.rol))

    db.commit()

    # El contrato se crea ahora: aparece en Contratos y el lote pasa a vendido
    venta_completa = svc.cargar_venta(db, venta.id, usuario)
    contrato = svc.generar_contrato_desde_venta(db, venta_completa, usuario)
    db.commit()

    venta_completa = svc.cargar_venta(db, venta.id, usuario)
    await _emitir_contrato_creado(db, contrato.id, venta_completa, usuario)
    return s.VentaOut.desde_venta(venta_completa)


@router.get("/por-separacion/{id_separacion}")
def venta_de_separacion(
    id_separacion: int,
    usuario: m.Usuario = Depends(require_permiso("ver_ventas")),
    db: Session = Depends(get_db),
):
    venta = db.query(m.Venta).filter(
        m.Venta.id_separacion == id_separacion,
        m.Venta.id_empresa == usuario.id_empresa,
    ).first()
    return {"id_venta": venta.id if venta else None}


@router.get("/por-contrato/{id_contrato}")
def venta_de_contrato(
    id_contrato: int,
    usuario: m.Usuario = Depends(require_permiso("ver_ventas")),
    db: Session = Depends(get_db),
):
    venta = db.query(m.Venta).filter(
        m.Venta.id_contrato == id_contrato,
        m.Venta.id_empresa == usuario.id_empresa,
    ).first()
    return {"id_venta": venta.id if venta else None}


@router.get("/{id_venta}", response_model=s.VentaOut)
def obtener_venta(
    id_venta: int,
    usuario: m.Usuario = Depends(require_permiso("ver_ventas")),
    db: Session = Depends(get_db),
):
    return s.VentaOut.desde_venta(svc.cargar_venta(db, id_venta, usuario))


@router.post("/{id_venta}/generar-documento", response_model=s.VentaOut)
async def generar_documento(
    id_venta: int,
    usuario: m.Usuario = Depends(require_permiso("crear_venta")),
    db: Session = Depends(get_db),
):
    venta = svc.cargar_venta(db, id_venta, usuario)
    pdf_bytes = svc.generar_documento_venta(db, venta)
    venta.documento_generado_url = svc.guardar_documento_pdf(venta.id, pdf_bytes)
    venta.estado = m.EstadoVentaEnum.documento_generado
    db.commit()
    venta_completa = svc.cargar_venta(db, id_venta, usuario)
    await notificar_venta("venta:actualizada", _resumen_socket(venta_completa), id_proyecto=venta.id_proyecto)
    return s.VentaOut.desde_venta(venta_completa)


@router.post("/{id_venta}/documento-firmado", response_model=s.VentaOut)
async def subir_documento_firmado(
    id_venta: int,
    payload: s.DocumentoFirmadoIn,
    usuario: m.Usuario = Depends(require_permiso("crear_venta")),
    db: Session = Depends(get_db),
):
    venta = svc.cargar_venta(db, id_venta, usuario)
    venta.documento_firmado_url = payload.url
    venta.estado = m.EstadoVentaEnum.documento_firmado
    db.commit()
    venta_completa = svc.cargar_venta(db, id_venta, usuario)
    await notificar_venta("venta:actualizada", _resumen_socket(venta_completa), id_proyecto=venta.id_proyecto)
    return s.VentaOut.desde_venta(venta_completa)


@router.post("/{id_venta}/ubicacion-documento", response_model=s.DocumentoUbicacionOut, status_code=status.HTTP_201_CREATED)
async def registrar_ubicacion_documento(
    id_venta: int,
    payload: s.DocumentoUbicacionCreate,
    usuario: m.Usuario = Depends(require_permiso("gestionar_rrpp")),
    db: Session = Depends(get_db),
):
    venta = svc.cargar_venta(db, id_venta, usuario)
    registro = m.DocumentoUbicacion(
        id_venta=venta.id, actualizado_por=usuario.id,
        **payload.model_dump(),
    )
    db.add(registro)
    db.commit()
    db.refresh(registro)
    await notificar_venta("venta:actualizada", _resumen_socket(venta), id_proyecto=venta.id_proyecto)
    return registro


@router.post("/{id_venta}/registrar-contrato", response_model=s.VentaOut)
async def registrar_contrato(
    id_venta: int,
    usuario: m.Usuario = Depends(require_permiso("crear_venta")),
    db: Session = Depends(get_db),
):
    venta = svc.cargar_venta(db, id_venta, usuario)
    contrato = svc.generar_contrato_desde_venta(db, venta, usuario)
    db.commit()

    venta_completa = svc.cargar_venta(db, id_venta, usuario)
    await _emitir_contrato_creado(db, contrato.id, venta_completa, usuario)
    return s.VentaOut.desde_venta(venta_completa)