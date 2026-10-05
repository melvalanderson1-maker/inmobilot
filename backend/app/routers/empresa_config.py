from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.deps import require_roles
from app.models import models as m
from app.schemas import schemas as s

router = APIRouter(prefix="/empresa", tags=["empresa"])


@router.get("/configuracion-legal", response_model=s.EmpresaConfigOut)
def obtener_configuracion_legal(
    usuario: m.Usuario = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    empresa = db.query(m.Empresa).filter(m.Empresa.id == usuario.id_empresa).first()
    if not empresa:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Empresa no encontrada")
    return empresa


@router.patch("/configuracion-legal", response_model=s.EmpresaConfigOut)
def actualizar_configuracion_legal(
    payload: s.EmpresaConfigUpdate,
    usuario: m.Usuario = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    empresa = db.query(m.Empresa).filter(m.Empresa.id == usuario.id_empresa).first()
    if not empresa:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Empresa no encontrada")

    for campo, valor in payload.model_dump(exclude_unset=True).items():
        setattr(empresa, campo, valor)

    db.commit()
    db.refresh(empresa)
    return empresa