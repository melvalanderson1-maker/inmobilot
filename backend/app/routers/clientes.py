from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.deps import require_permiso
from app.models import models as m
from app.schemas import schemas as s

router = APIRouter(prefix="/clientes", tags=["clientes"])


@router.get("/buscar", response_model=Optional[s.ClienteOut])
def buscar_cliente_por_documento(
    documento: str,
    usuario: m.Usuario = Depends(require_permiso("crear_separacion")),
    db: Session = Depends(get_db),
):
    """Devuelve el cliente, o null si no existe (para que el formulario pida crearlo)."""
    return (
        db.query(m.Cliente)
        .filter(
            m.Cliente.id_empresa == usuario.id_empresa,
            m.Cliente.numero_documento == documento.strip(),
        )
        .first()
    )


@router.post("", response_model=s.ClienteOut, status_code=status.HTTP_201_CREATED)
def crear_cliente(
    payload: s.ClienteCreate,
    usuario: m.Usuario = Depends(require_permiso("crear_separacion")),
    db: Session = Depends(get_db),
):
    tipo = payload.tipo_documento.strip().upper()
    numero = payload.numero_documento.strip()

    if tipo == "DNI" and not (numero.isdigit() and len(numero) == 8):
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
        tipo_documento=tipo,
        numero_documento=numero,
        nombres=payload.nombres.strip(),
        apellidos=payload.apellidos.strip(),
        correo=payload.correo,
        telefono=payload.telefono.strip(),
        direccion=payload.direccion.strip(),
    )
    db.add(cliente)
    db.commit()
    db.refresh(cliente)
    return cliente