import os
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import hash_password
from app.deps import require_modulo, require_roles, get_current_user
from app.models import models as m
from app.schemas import schemas as s
from app.services.documento_separacion import DIR_FIRMAS
from app.sockets import notificar_actualizacion_proyectos

router = APIRouter(prefix="/usuarios", tags=["usuarios"])

MAX_FIRMA_BYTES = 2 * 1024 * 1024
_FIRMAS_VALIDAS = ((b"\x89PNG\r\n\x1a\n", "png"), (b"\xff\xd8\xff", "jpg"))  # por contenido real, no por extensión


def _borrar_archivo_firma(nombre: str | None) -> None:
    if not nombre:
        return
    try:
        os.remove(os.path.join(DIR_FIRMAS, os.path.basename(nombre)))
    except FileNotFoundError:
        pass


@router.get("", response_model=list[s.UsuarioOut])
def listar_usuarios(
    usuario: m.Usuario = Depends(require_modulo("usuarios")),
    db: Session = Depends(get_db),
):
    usuarios = db.query(m.Usuario).filter(m.Usuario.id_empresa == usuario.id_empresa).all()
    return [s.UsuarioOut.desde_usuario(u) for u in usuarios]


@router.get("/{id_usuario}", response_model=s.UsuarioOut)
def obtener_usuario(
    id_usuario: int,
    usuario: m.Usuario = Depends(require_modulo("usuarios")),
    db: Session = Depends(get_db),
):
    obj = db.query(m.Usuario).filter(m.Usuario.id == id_usuario, m.Usuario.id_empresa == usuario.id_empresa).first()
    if not obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado")
    return s.UsuarioOut.desde_usuario(obj)


@router.post("", response_model=s.UsuarioOut, status_code=status.HTTP_201_CREATED)
def crear_usuario(
    payload: s.UsuarioCreate,
    usuario: m.Usuario = Depends(require_roles("admin", "gerencia")),
    db: Session = Depends(get_db),
):
    existe = db.query(m.Usuario).filter(m.Usuario.correo == payload.correo).first()
    if existe:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Ese correo ya está registrado")

    nuevo = m.Usuario(
        nombre=payload.nombre,
        correo=payload.correo,
        password_hash=hash_password(payload.password),
        telefono=payload.telefono,
        id_rol=payload.id_rol,
        id_empresa=payload.id_empresa or usuario.id_empresa,
    )
    db.add(nuevo)
    db.commit()
    db.refresh(nuevo)

    if payload.proyectos:
        for id_proyecto in payload.proyectos:
            db.add(m.UsuarioProyecto(id_usuario=nuevo.id, id_proyecto=id_proyecto))
        db.commit()
        db.refresh(nuevo)

    return s.UsuarioOut.desde_usuario(nuevo)


@router.patch("/{id_usuario}", response_model=s.UsuarioOut)
async def actualizar_usuario(
    id_usuario: int,
    payload: s.UsuarioUpdate,
    usuario: m.Usuario = Depends(require_roles("admin", "gerencia")),
    db: Session = Depends(get_db),
):
    obj = db.query(m.Usuario).filter(m.Usuario.id == id_usuario, m.Usuario.id_empresa == usuario.id_empresa).first()
    if not obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado")

    datos = payload.model_dump(exclude_unset=True, exclude={"password", "proyectos"})
    for campo, valor in datos.items():
        setattr(obj, campo, valor)

    if payload.password:
        obj.password_hash = hash_password(payload.password)

    if payload.proyectos is not None:
        db.query(m.UsuarioProyecto).filter(m.UsuarioProyecto.id_usuario == obj.id).delete()
        for id_proyecto in payload.proyectos:
            db.add(m.UsuarioProyecto(id_usuario=obj.id, id_proyecto=id_proyecto))

    db.commit()
    db.refresh(obj)

    if payload.proyectos is not None:
        await notificar_actualizacion_proyectos(obj.id)

    return s.UsuarioOut.desde_usuario(obj)

@router.delete("/{id_usuario}", status_code=status.HTTP_204_NO_CONTENT)
def desactivar_usuario(
    id_usuario: int,
    usuario: m.Usuario = Depends(require_roles("admin", "gerencia")),
    db: Session = Depends(get_db),
):
    obj = db.query(m.Usuario).filter(m.Usuario.id == id_usuario, m.Usuario.id_empresa == usuario.id_empresa).first()
    if not obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado")
    if obj.id == usuario.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No puedes desactivarte a ti mismo")

    obj.activo = False
    db.commit()


@router.patch("/{id_usuario}/activar", response_model=s.UsuarioOut)
def activar_usuario(
    id_usuario: int,
    usuario: m.Usuario = Depends(require_roles("admin", "gerencia")),
    db: Session = Depends(get_db),
):
    obj = db.query(m.Usuario).filter(m.Usuario.id == id_usuario, m.Usuario.id_empresa == usuario.id_empresa).first()
    if not obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado")

    obj.activo = True
    db.commit()
    db.refresh(obj)

    return s.UsuarioOut.desde_usuario(obj)


@router.get("/roles/lista", response_model=list[s.RolOut])
def listar_roles(
    usuario: m.Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return db.query(m.Rol).filter(
        (m.Rol.id_empresa == usuario.id_empresa) | (m.Rol.id_empresa.is_(None))
    ).all()


@router.post("/{id_usuario}/firma", response_model=s.UsuarioOut)
async def subir_firma(
    id_usuario: int,
    archivo: UploadFile = File(...),
    usuario: m.Usuario = Depends(require_roles("admin", "gerencia")),
    db: Session = Depends(get_db),
):
    """Carga (o reemplaza) la firma que saldrá en las proformas y contratos de separación de este usuario."""
    obj = db.query(m.Usuario).filter(m.Usuario.id == id_usuario, m.Usuario.id_empresa == usuario.id_empresa).first()
    if not obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado")

    contenido = await archivo.read(MAX_FIRMA_BYTES + 1)
    if len(contenido) > MAX_FIRMA_BYTES:
        raise HTTPException(status_code=422, detail="La firma debe pesar menos de 2 MB")
    extension = next((ext for magic, ext in _FIRMAS_VALIDAS if contenido.startswith(magic)), None)
    if not extension:
        raise HTTPException(status_code=422, detail="La firma debe ser una imagen PNG o JPG")

    nombre = f"firma_{obj.id}_{uuid.uuid4().hex[:8]}.{extension}"
    with open(os.path.join(DIR_FIRMAS, nombre), "wb") as f:
        f.write(contenido)

    anterior = obj.firma_archivo
    obj.firma_archivo = nombre
    db.commit()
    _borrar_archivo_firma(anterior)
    db.refresh(obj)
    return s.UsuarioOut.desde_usuario(obj)


@router.delete("/{id_usuario}/firma", response_model=s.UsuarioOut)
def eliminar_firma(
    id_usuario: int,
    usuario: m.Usuario = Depends(require_roles("admin", "gerencia")),
    db: Session = Depends(get_db),
):
    obj = db.query(m.Usuario).filter(m.Usuario.id == id_usuario, m.Usuario.id_empresa == usuario.id_empresa).first()
    if not obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado")

    anterior = obj.firma_archivo
    obj.firma_archivo = None
    db.commit()
    _borrar_archivo_firma(anterior)
    db.refresh(obj)
    return s.UsuarioOut.desde_usuario(obj)