from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload, selectinload

from app.core.database import get_db
from app.deps import require_permiso, get_ids_proyectos_usuario
from app.models import models as m
from app.schemas import schemas as s

router = APIRouter(prefix="/clientes", tags=["clientes"])


def _aplicar_conyuge(db: Session, cliente: m.Cliente, datos_conyuge: Optional[s.ClienteConyugeIn]) -> None:
    if datos_conyuge is None:
        return
    existente = db.query(m.ClienteConyuge).filter(m.ClienteConyuge.id_cliente == cliente.id).first()
    if existente:
        existente.nombres = datos_conyuge.nombres.strip()
        existente.apellidos = datos_conyuge.apellidos.strip()
        existente.numero_documento = datos_conyuge.numero_documento.strip()
        existente.telefono = datos_conyuge.telefono
        existente.dni_frente_url = datos_conyuge.dni_frente_url
        existente.dni_reverso_url = datos_conyuge.dni_reverso_url
    else:
        db.add(m.ClienteConyuge(
            id_cliente=cliente.id,
            nombres=datos_conyuge.nombres.strip(),
            apellidos=datos_conyuge.apellidos.strip(),
            numero_documento=datos_conyuge.numero_documento.strip(),
            telefono=datos_conyuge.telefono,
            dni_frente_url=datos_conyuge.dni_frente_url,
            dni_reverso_url=datos_conyuge.dni_reverso_url,
        ))


@router.get("/buscar", response_model=Optional[s.ClienteOut])
def buscar_cliente_por_documento(
    documento: str,
    usuario: m.Usuario = Depends(require_permiso("ver_clientes")),
    db: Session = Depends(get_db),
):
    """Devuelve el cliente, o null si no existe (usado por el formulario de separación)."""
    return (
        db.query(m.Cliente)
        .options(joinedload(m.Cliente.conyuge))
        .filter(
            m.Cliente.id_empresa == usuario.id_empresa,
            m.Cliente.numero_documento == documento.strip(),
        )
        .first()
    )


@router.get("", response_model=list[s.ClienteOut])
def listar_clientes(
    busqueda: Optional[str] = None,
    tipo_persona: Optional[str] = None,
    activo: Optional[bool] = None,
    usuario: m.Usuario = Depends(require_permiso("ver_clientes")),
    db: Session = Depends(get_db),
):
    query = (
        db.query(m.Cliente)
        .options(joinedload(m.Cliente.conyuge))
        .filter(m.Cliente.id_empresa == usuario.id_empresa)
    )

    if tipo_persona:
        query = query.filter(m.Cliente.tipo_persona == tipo_persona)
    if activo is not None:
        query = query.filter(m.Cliente.activo == activo)
    if busqueda:
        texto = f"%{busqueda.strip()}%"
        query = query.filter(
            (m.Cliente.nombres.ilike(texto))
            | (m.Cliente.apellidos.ilike(texto))
            | (m.Cliente.numero_documento.ilike(texto))
            | (m.Cliente.razon_social.ilike(texto))
            | (m.Cliente.telefono.ilike(texto))
        )

    return query.order_by(m.Cliente.created_at.desc()).limit(200).all()


@router.get("/{id_cliente}", response_model=s.ClienteDetalleOut)
def obtener_cliente(
    id_cliente: int,
    usuario: m.Usuario = Depends(require_permiso("ver_clientes")),
    db: Session = Depends(get_db),
):
    cliente = (
        db.query(m.Cliente)
        .options(joinedload(m.Cliente.conyuge))
        .filter(m.Cliente.id == id_cliente, m.Cliente.id_empresa == usuario.id_empresa)
        .first()
    )
    if not cliente:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cliente no encontrado")

    ids_proyectos = get_ids_proyectos_usuario(db, usuario)
    query_sep = (
        db.query(m.Separacion)
        .options(joinedload(m.Separacion.lote))
        .filter(m.Separacion.id_cliente == id_cliente)
    )
    if ids_proyectos is not None:
        query_sep = query_sep.filter(m.Separacion.id_proyecto.in_(ids_proyectos))
    separaciones = query_sep.order_by(m.Separacion.created_at.desc()).all()

    data = s.ClienteDetalleOut.model_validate(cliente)
    data.separaciones = [
        s.ClienteHistorialSeparacionOut(
            id=sep.id,
            id_proyecto=sep.id_proyecto,
            estado=sep.estado,
            importe=sep.importe,
            created_at=sep.created_at,
            lote_codigo=sep.lote.codigo if sep.lote else None,
        )
        for sep in separaciones
    ]
    return data


@router.post("", response_model=s.ClienteOut, status_code=status.HTTP_201_CREATED)
def crear_cliente(
    payload: s.ClienteCreate,
    usuario: m.Usuario = Depends(require_permiso("crear_separacion")),
    db: Session = Depends(get_db),
):
    tipo = payload.tipo_documento.strip().upper()
    numero = payload.numero_documento.strip()

    if payload.tipo_persona == "natural" and tipo == "DNI" and not (numero.isdigit() and len(numero) == 8):
        raise HTTPException(status_code=422, detail="El DNI debe tener 8 dígitos")
    if not payload.telefono or not payload.telefono.strip():
        raise HTTPException(status_code=422, detail="El teléfono es obligatorio")
    if not payload.direccion or not payload.direccion.strip():
        raise HTTPException(status_code=422, detail="La dirección es obligatoria")

    existe = (
        db.query(m.Cliente)
        .filter(m.Cliente.id_empresa == usuario.id_empresa, m.Cliente.numero_documento == numero)
        .first()
    )
    if existe:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Ya existe un cliente con ese documento")

    cliente = m.Cliente(
        id_empresa=usuario.id_empresa,
        tipo_persona=payload.tipo_persona,
        tipo_documento=tipo,
        numero_documento=numero,
        nombres=payload.nombres.strip(),
        apellidos=payload.apellidos.strip(),
        correo=payload.correo,
        telefono=payload.telefono.strip(),
        direccion=payload.direccion.strip(),
        dni_frente_url=payload.dni_frente_url,
        dni_reverso_url=payload.dni_reverso_url,
        fecha_nacimiento=payload.fecha_nacimiento,
        estado_civil=payload.estado_civil,
        segundo_contacto_nombre=payload.segundo_contacto_nombre,
        segundo_contacto_telefono=payload.segundo_contacto_telefono,
        ruc=payload.ruc,
        razon_social=payload.razon_social,
        representante_legal=payload.representante_legal,
    )
    db.add(cliente)
    db.flush()

    _aplicar_conyuge(db, cliente, payload.conyuge)

    db.commit()
    db.refresh(cliente)

    cliente_completo = (
        db.query(m.Cliente).options(joinedload(m.Cliente.conyuge)).filter(m.Cliente.id == cliente.id).first()
    )
    return cliente_completo


@router.patch("/{id_cliente}", response_model=s.ClienteOut)
def actualizar_cliente(
    id_cliente: int,
    payload: s.ClienteUpdate,
    usuario: m.Usuario = Depends(require_permiso("editar_cliente")),
    db: Session = Depends(get_db),
):
    cliente = (
        db.query(m.Cliente)
        .filter(m.Cliente.id == id_cliente, m.Cliente.id_empresa == usuario.id_empresa)
        .first()
    )
    if not cliente:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cliente no encontrado")

    datos = payload.model_dump(exclude_unset=True, exclude={"conyuge"})
    for campo, valor in datos.items():
        setattr(cliente, campo, valor)

    if "conyuge" in payload.model_fields_set:
        _aplicar_conyuge(db, cliente, payload.conyuge)

    db.commit()
    db.refresh(cliente)

    cliente_completo = (
        db.query(m.Cliente).options(joinedload(m.Cliente.conyuge)).filter(m.Cliente.id == cliente.id).first()
    )
    return cliente_completo