from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from app.core.database import get_db
from app.deps import require_permiso
from app.models import models as m

router = APIRouter(prefix="/auditoria", tags=["auditoria"])


@router.get("")
def listar_auditoria(
    entidad: Optional[str] = None,
    id_entidad: Optional[int] = None,
    limite: int = 200,
    usuario: m.Usuario = Depends(require_permiso("ver_clientes")),
    db: Session = Depends(get_db),
):
    if usuario.rol.clave not in ("admin", "gerencia"):
        raise HTTPException(status_code=403, detail="Solo admin o gerencia pueden ver la auditoría")

    q = (
        db.query(m.Auditoria)
        .options(joinedload(m.Auditoria.usuario))
        .filter(m.Auditoria.id_empresa == usuario.id_empresa)
    )
    if entidad:
        q = q.filter(m.Auditoria.entidad == entidad)
    if id_entidad is not None:
        q = q.filter(m.Auditoria.id_entidad == id_entidad)

    filas = q.order_by(m.Auditoria.created_at.desc()).limit(max(1, min(limite, 500))).all()
    return [
        {
            "id": f.id,
            "entidad": f.entidad,
            "id_entidad": f.id_entidad,
            "accion": f.accion,
            "usuario": f.usuario.nombre if f.usuario else None,
            "fecha": f.created_at.isoformat() if f.created_at else None,
            "cambios": f.cambios,
        }
        for f in filas
    ]