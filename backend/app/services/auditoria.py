from datetime import date, datetime
from decimal import Decimal
import enum

from sqlalchemy.orm import Session

from app.models import models as m


def _plano(v):
    if isinstance(v, enum.Enum):
        return v.value
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return format(v.normalize(), "f")
    return v


def diferencias(antes: dict, despues: dict) -> dict:
    """Compara solo las claves de `despues`. Devuelve {campo: {antes, despues}} de lo que cambió."""
    salida = {}
    for campo, nuevo in despues.items():
        ant = antes.get(campo)
        if _plano(ant) != _plano(nuevo):
            salida[campo] = {"antes": _plano(ant), "despues": _plano(nuevo)}
    return salida


def registrar(db: Session, usuario: m.Usuario, entidad: str, id_entidad: int, accion: str, cambios: dict | None = None) -> None:
    """Se agrega a la misma transacción: se guarda con el db.commit() del endpoint."""
    db.add(m.Auditoria(
        id_empresa=usuario.id_empresa,
        id_usuario=usuario.id,
        entidad=entidad,
        id_entidad=id_entidad,
        accion=accion,
        cambios=cambios,
    ))