from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import decode_access_token
from app.models import models as m

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> m.Usuario:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="No se pudo validar la credencial",
        headers={"WWW-Authenticate": "Bearer"},
    )
    payload = decode_access_token(token)
    if payload is None:
        raise credentials_exception

    user_id = payload.get("sub")
    if user_id is None:
        raise credentials_exception

    usuario = db.query(m.Usuario).filter(m.Usuario.id == int(user_id)).first()
    if usuario is None or not usuario.activo:
        raise credentials_exception

    return usuario


def get_usuario_modulos_claves(db: Session, usuario: m.Usuario) -> set[str]:
    """Módulos habilitados por el rol, ajustados por permisos finos del usuario."""
    base = {mod.clave for mod in usuario.rol.modulos}

    permisos = (
        db.query(m.UsuarioModuloPermiso)
        .filter(m.UsuarioModuloPermiso.id_usuario == usuario.id)
        .all()
    )
    for permiso in permisos:
        modulo = db.query(m.Modulo).filter(m.Modulo.id == permiso.id_modulo).first()
        if not modulo:
            continue
        if permiso.habilitado:
            base.add(modulo.clave)
        else:
            base.discard(modulo.clave)

    return base


def require_modulo(clave_modulo: str):
    """Factory de dependencia: exige que el usuario tenga acceso al módulo dado."""

    def _checker(
        usuario: m.Usuario = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> m.Usuario:
        claves = get_usuario_modulos_claves(db, usuario)
        if clave_modulo not in claves and usuario.rol.clave != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"No tienes acceso al módulo '{clave_modulo}'",
            )
        return usuario

    return _checker


def require_roles(*roles_permitidos: str):
    """Factory de dependencia: exige que el usuario tenga uno de los roles dados."""

    def _checker(usuario: m.Usuario = Depends(get_current_user)) -> m.Usuario:
        if usuario.rol.clave not in roles_permitidos:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes el rol necesario para esta acción",
            )
        return usuario

    return _checker


def get_ids_proyectos_usuario(db: Session, usuario: m.Usuario) -> list[int] | None:
    """None significa 'todos los proyectos de su empresa' (admin/gerencia)."""
    if usuario.rol.clave in ("admin", "gerencia"):
        return None
    filas = (
        db.query(m.UsuarioProyecto.id_proyecto)
        .filter(m.UsuarioProyecto.id_usuario == usuario.id)
        .all()
    )
    return [f[0] for f in filas]
