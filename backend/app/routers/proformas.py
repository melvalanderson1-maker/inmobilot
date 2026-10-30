from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from app.core.database import get_db
from app.deps import require_permiso
from app.models import models as m
from app.schemas import schemas as s
from app.services import separacion_service as svc

router = APIRouter(prefix="/proformas", tags=["proformas"])

LOTE = m.EstadoLoteEnum


def _query(db: Session):
    return db.query(m.Proforma).options(
        joinedload(m.Proforma.lote),
        joinedload(m.Proforma.cliente),
        joinedload(m.Proforma.ejecutivo),
    )


def _cargar(db: Session, id_proforma: int, usuario: m.Usuario) -> m.Proforma:
    pf = _query(db).filter(m.Proforma.id == id_proforma, m.Proforma.id_empresa == usuario.id_empresa).first()
    if not pf:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proforma no encontrada")
    svc.validar_acceso_proyecto(db, usuario, pf.id_proyecto)
    if usuario.rol.clave == "ejecutivo_ventas" and pf.id_ejecutivo != usuario.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Esta proforma pertenece a otro ejecutivo")
    return pf


# ---------------------------------------------------------------- lectura --

@router.get("", response_model=list[s.ProformaOut])
def listar_proformas(
    id_proyecto: int,
    buscar: Optional[str] = None,
    usuario: m.Usuario = Depends(require_permiso("ver_separaciones")),
    db: Session = Depends(get_db),
):
    svc.validar_acceso_proyecto(db, usuario, id_proyecto)
    query = _query(db).filter(m.Proforma.id_empresa == usuario.id_empresa, m.Proforma.id_proyecto == id_proyecto)
    if usuario.rol.clave == "ejecutivo_ventas":
        query = query.filter(m.Proforma.id_ejecutivo == usuario.id)
    if buscar and buscar.strip():
        patron = f"%{buscar.strip()}%"
        query = query.filter(or_(
            m.Proforma.prospecto_nombre.ilike(patron),
            m.Proforma.prospecto_documento.ilike(patron),
            m.Proforma.prospecto_telefono.ilike(patron),
        ))
    return [s.ProformaOut.desde_proforma(p) for p in query.order_by(m.Proforma.created_at.desc()).limit(200).all()]


@router.get("/{id_proforma}", response_model=s.ProformaOut)
def obtener_proforma(
    id_proforma: int,
    usuario: m.Usuario = Depends(require_permiso("ver_separaciones")),
    db: Session = Depends(get_db),
):
    return s.ProformaOut.desde_proforma(_cargar(db, id_proforma, usuario))


# ------------------------------------------------------------------ crear --

@router.post("", response_model=s.ProformaOut, status_code=status.HTTP_201_CREATED)
def crear_proforma(
    payload: s.ProformaCreate,
    usuario: m.Usuario = Depends(require_permiso("crear_separacion")),
    db: Session = Depends(get_db),
):
    """Proforma rápida: no separa el lote ni cambia su estado. Si el cliente decide separar, se vincula después."""
    lote = db.query(m.Lote).filter(m.Lote.id == payload.id_lote).first()
    if not lote or not lote.activo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lote no encontrado")
    svc.validar_acceso_proyecto(db, usuario, lote.id_proyecto)
    if lote.estado != LOTE.libre:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"El lote {lote.codigo} no está libre (estado actual: {lote.estado.value})",
        )
    if payload.precio_valido_hasta < svc.hoy_peru():
        raise HTTPException(status_code=422, detail="La validez del precio no puede ser anterior a hoy")
    svc.validar_precio_descontado(lote, payload.precio_descontado, payload.tipo_pago)

    id_cliente = None
    if payload.id_cliente:
        cliente = (
            db.query(m.Cliente)
            .filter(m.Cliente.id == payload.id_cliente, m.Cliente.id_empresa == usuario.id_empresa)
            .first()
        )
        if not cliente:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cliente no encontrado")
        id_cliente = cliente.id

    pf = m.Proforma(
        id_empresa=usuario.id_empresa,
        id_proyecto=lote.id_proyecto,
        id_lote=lote.id,
        id_cliente=id_cliente,
        id_ejecutivo=usuario.id,
        prospecto_nombre=(payload.prospecto_nombre or "").strip() or None,
        prospecto_documento=(payload.prospecto_documento or "").strip() or None,
        prospecto_telefono=(payload.prospecto_telefono or "").strip() or None,
        tipo_pago=payload.tipo_pago.value if payload.tipo_pago else None,
        precio_descontado=payload.precio_descontado,
        precio_valido_hasta=payload.precio_valido_hasta,
        importe=payload.importe,
        fecha_emision=svc.hoy_peru(),
        estado="emitida",
    )
    db.add(pf)
    db.flush()
    pf.documento_url = svc.generar_documento_proforma(db, pf)
    db.commit()
    return s.ProformaOut.desde_proforma(_cargar(db, pf.id, usuario))