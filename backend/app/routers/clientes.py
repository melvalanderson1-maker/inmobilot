from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload, selectinload

from app.core.database import get_db
from app.deps import require_permiso, get_ids_proyectos_usuario
from app.models import models as m
from app.schemas import schemas as s

from app.services import auditoria as aud

router = APIRouter(prefix="/clientes", tags=["clientes"])


CAMPOS_CONYUGE = ("nombres", "apellidos", "numero_documento", "telefono", "direccion", "dni_frente_url", "dni_reverso_url")


def _aplicar_conyuge(db: Session, cliente: m.Cliente, datos_conyuge: Optional[s.ClienteConyugeIn]) -> None:
    if datos_conyuge is None:
        return
    existente = db.query(m.ClienteConyuge).filter(m.ClienteConyuge.id_cliente == cliente.id).first()
    if existente:
        existente.nombres = datos_conyuge.nombres.strip()
        existente.apellidos = datos_conyuge.apellidos.strip()
        existente.numero_documento = datos_conyuge.numero_documento.strip()
        existente.telefono = datos_conyuge.telefono
        existente.direccion = datos_conyuge.direccion
        existente.dni_frente_url = datos_conyuge.dni_frente_url
        existente.dni_reverso_url = datos_conyuge.dni_reverso_url
    else:
        db.add(m.ClienteConyuge(
            id_cliente=cliente.id,
            nombres=datos_conyuge.nombres.strip(),
            apellidos=datos_conyuge.apellidos.strip(),
            numero_documento=datos_conyuge.numero_documento.strip(),
            telefono=datos_conyuge.telefono,
            direccion=datos_conyuge.direccion,
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
    limite: int = 200,
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
        # Cada palabra debe aparecer en algún campo: "erick melendez" encuentra a "Erick Anderson Melendez"
        for palabra in busqueda.strip().split():
            texto = f"%{palabra}%"
            query = query.filter(
                (m.Cliente.nombres.ilike(texto))
                | (m.Cliente.apellidos.ilike(texto))
                | (m.Cliente.numero_documento.ilike(texto))
                | (m.Cliente.razon_social.ilike(texto))
                | (m.Cliente.ruc.ilike(texto))
                | (m.Cliente.telefono.ilike(texto))
            )

    return query.order_by(m.Cliente.created_at.desc()).limit(max(1, min(limite, 200))).all()


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
        sexo=payload.sexo,
        segundo_contacto_nombre=payload.segundo_contacto_nombre,
        segundo_contacto_telefono=payload.segundo_contacto_telefono,
        ruc=payload.ruc,
        razon_social=payload.razon_social,
        representante_legal=payload.representante_legal,
        representante_tipo_documento=payload.representante_tipo_documento,
        representante_numero_documento=payload.representante_numero_documento,
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

    for campo in ("nombres", "apellidos"):
        if campo in datos:
            valor = (datos[campo] or "").strip()
            if not valor:
                raise HTTPException(status_code=422, detail=f"El campo {campo} no puede quedar vacío")
            datos[campo] = valor

    if "tipo_documento" in datos:
        datos["tipo_documento"] = (datos["tipo_documento"] or "").strip().upper() or cliente.tipo_documento

    if "numero_documento" in datos:
        numero = (datos["numero_documento"] or "").strip()
        if not numero:
            raise HTTPException(status_code=422, detail="El número de documento no puede quedar vacío")
        repetido = (
            db.query(m.Cliente.id)
            .filter(
                m.Cliente.id_empresa == usuario.id_empresa,
                m.Cliente.numero_documento == numero,
                m.Cliente.id != id_cliente,
            )
            .first()
        )
        if repetido:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Ya existe otro cliente con ese documento")
        datos["numero_documento"] = numero

    # --- auditoría: lo que cambia en el cliente (antes de aplicar) ---
    cambios = aud.diferencias({c: getattr(cliente, c) for c in datos}, datos)

    for campo, valor in datos.items():
        setattr(cliente, campo, valor)

    # --- cónyuge ---
    conyuge_previo = db.query(m.ClienteConyuge).filter(m.ClienteConyuge.id_cliente == cliente.id).first()

    if "estado_civil" in datos and datos["estado_civil"] != "casado":
        # Dejó de ser casado: se elimina el cónyuge (queda guardado en la auditoría)
        if conyuge_previo:
            cambios["conyuge_eliminado"] = {c: getattr(conyuge_previo, c) for c in CAMPOS_CONYUGE}
            db.delete(conyuge_previo)
    elif "conyuge" in payload.model_fields_set and payload.conyuge is not None:
        nuevo = {
            c: (v.strip() if isinstance(v, str) else v)
            for c, v in ((c, getattr(payload.conyuge, c)) for c in CAMPOS_CONYUGE)
        }
        if conyuge_previo:
            antes = {c: getattr(conyuge_previo, c) for c in CAMPOS_CONYUGE}
            dif = aud.diferencias(antes, nuevo)
            if dif:
                cambios["conyuge"] = dif
        else:
            cambios["conyuge_agregado"] = nuevo
        _aplicar_conyuge(db, cliente, payload.conyuge)

    if cambios:
        aud.registrar(db, usuario, "cliente", cliente.id, "editar", cambios)

    db.commit()
    db.refresh(cliente)

    return (
        db.query(m.Cliente).options(joinedload(m.Cliente.conyuge)).filter(m.Cliente.id == cliente.id).first()
    )


@router.post("/{id_cliente}/conyuge-como-cliente", response_model=s.ClienteOut)
def conyuge_como_cliente(
    id_cliente: int,
    usuario: m.Usuario = Depends(require_permiso("crear_venta")),
    db: Session = Depends(get_db),
):
    """Convierte al cónyuge registrado en un Cliente propio, para que pueda ser
    titular o segundo comprador. Si ya existe como cliente, devuelve ese."""
    titular = (
        db.query(m.Cliente)
        .options(joinedload(m.Cliente.conyuge))
        .filter(m.Cliente.id == id_cliente, m.Cliente.id_empresa == usuario.id_empresa)
        .first()
    )
    if not titular:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cliente no encontrado")
    if not titular.conyuge:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Este cliente no tiene cónyuge registrado")

    cy = titular.conyuge
    documento = cy.numero_documento.strip()
    existente = (
        db.query(m.Cliente)
        .filter(m.Cliente.id_empresa == usuario.id_empresa, m.Cliente.numero_documento == documento)
        .first()
    )
    id_resultado = existente.id if existente else None

    if not existente:
        nuevo = m.Cliente(
            id_empresa=usuario.id_empresa,
            tipo_persona="natural",
            tipo_documento="DNI",
            numero_documento=documento,
            nombres=cy.nombres,
            apellidos=cy.apellidos,
            telefono=cy.telefono or titular.telefono,
            direccion=cy.direccion or titular.direccion,
            dni_frente_url=cy.dni_frente_url,
            dni_reverso_url=cy.dni_reverso_url,
            estado_civil="casado",
        )
        db.add(nuevo)
        db.flush()
        # Cónyuge en espejo: ella queda casada con el titular (solo si el titular es persona natural)
        if titular.tipo_persona == "natural":
            db.add(m.ClienteConyuge(
                id_cliente=nuevo.id,
                nombres=titular.nombres,
                apellidos=titular.apellidos,
                numero_documento=titular.numero_documento,
                telefono=titular.telefono,
                direccion=titular.direccion,
                dni_frente_url=titular.dni_frente_url,
                dni_reverso_url=titular.dni_reverso_url,
            ))
        db.commit()
        id_resultado = nuevo.id

    return (
        db.query(m.Cliente)
        .options(joinedload(m.Cliente.conyuge))
        .filter(m.Cliente.id == id_resultado)
        .first()
    )



@router.delete("/{id_cliente}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar_cliente(
    id_cliente: int,
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

    en_uso = (
        db.query(m.Separacion.id).filter(m.Separacion.id_cliente == id_cliente).first()
        or db.query(m.VentaCliente.id_venta).filter(m.VentaCliente.id_cliente == id_cliente).first()
        or db.query(m.ContratoCliente.id_contrato).filter(m.ContratoCliente.id_cliente == id_cliente).first()
        or db.query(m.Proforma.id).filter(m.Proforma.id_cliente == id_cliente).first()
    )
    if en_uso:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="El cliente ya tiene separaciones, ventas, contratos o proformas. No se puede eliminar; desactívalo.",
        )

    snapshot = {
        "tipo_documento": cliente.tipo_documento,
        "numero_documento": cliente.numero_documento,
        "nombres": cliente.nombres,
        "apellidos": cliente.apellidos,
        "razon_social": cliente.razon_social,
    }
    conyuge = db.query(m.ClienteConyuge).filter(m.ClienteConyuge.id_cliente == id_cliente).first()
    if conyuge:
        snapshot["conyuge"] = {c: getattr(conyuge, c) for c in CAMPOS_CONYUGE}
        db.delete(conyuge)   # explícito: la relación ORM no tiene cascade

    aud.registrar(db, usuario, "cliente", cliente.id, "eliminar", snapshot)
    db.delete(cliente)
    db.commit()