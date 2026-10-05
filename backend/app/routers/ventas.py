from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload, selectinload

from app.core.database import get_db
from app.deps import require_permiso
from app.models import models as m
from app.schemas import schemas as s
from app.services import venta_service as svc
from app.sockets import notificar_venta

router = APIRouter(prefix="/ventas", tags=["ventas"])


def _resumen_socket(venta: m.Venta) -> dict:
    return {"id": venta.id, "id_lote": venta.id_lote, "estado": venta.estado.value}


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
    venta_completa = svc.cargar_venta(db, venta.id, usuario)
    await notificar_venta("venta:nueva", _resumen_socket(venta_completa), id_proyecto=venta.id_proyecto)
    return s.VentaOut.desde_venta(venta_completa)


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