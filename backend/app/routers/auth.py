from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import verify_password, create_access_token
from app.deps import get_current_user, get_usuario_modulos_claves
from app.models import models as m
from app.schemas import schemas as s

router = APIRouter(prefix="/auth", tags=["auth"])


def _build_token_response(db: Session, usuario: m.Usuario) -> s.TokenResponse:
    claves_modulos = get_usuario_modulos_claves(db, usuario)
    modulos = db.query(m.Modulo).filter(m.Modulo.clave.in_(claves_modulos)).all()

    ids_proyecto = [
        row[0]
        for row in db.query(m.UsuarioProyecto.id_proyecto)
        .filter(m.UsuarioProyecto.id_usuario == usuario.id)
        .all()
    ]

    token = create_access_token(
        {
            "sub": str(usuario.id),
            "id_empresa": usuario.id_empresa,
            "rol": usuario.rol.clave,
            "proyectos": ids_proyecto,
        }
    )

    usuario_out = s.UsuarioMeOut(
        id=usuario.id,
        nombre=usuario.nombre,
        correo=usuario.correo,
        telefono=usuario.telefono,
        rol=s.RolOut.model_validate(usuario.rol),
        id_empresa=usuario.id_empresa,
        modulos=[s.ModuloOut.model_validate(mod) for mod in modulos],
        proyectos=ids_proyecto,
    )

    return s.TokenResponse(access_token=token, usuario=usuario_out)


@router.post("/login", response_model=s.TokenResponse)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    usuario = db.query(m.Usuario).filter(m.Usuario.correo == form_data.username).first()

    if not usuario or not verify_password(form_data.password, usuario.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Correo o contraseña incorrectos",
        )
    if not usuario.activo:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Usuario inactivo")

    return _build_token_response(db, usuario)


@router.post("/login-json", response_model=s.TokenResponse)
def login_json(payload: s.LoginRequest, db: Session = Depends(get_db)):
    """Alternativa a /auth/login que acepta JSON en vez de form-data (útil para el frontend Angular)."""
    usuario = db.query(m.Usuario).filter(m.Usuario.correo == payload.correo).first()

    if not usuario or not verify_password(payload.password, usuario.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Correo o contraseña incorrectos",
        )
    if not usuario.activo:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Usuario inactivo")

    return _build_token_response(db, usuario)


@router.get("/me", response_model=s.UsuarioMeOut)
def me(usuario: m.Usuario = Depends(get_current_user), db: Session = Depends(get_db)):
    claves_modulos = get_usuario_modulos_claves(db, usuario)
    modulos = db.query(m.Modulo).filter(m.Modulo.clave.in_(claves_modulos)).all()
    ids_proyecto = [
        row[0]
        for row in db.query(m.UsuarioProyecto.id_proyecto)
        .filter(m.UsuarioProyecto.id_usuario == usuario.id)
        .all()
    ]
    return s.UsuarioMeOut(
        id=usuario.id,
        nombre=usuario.nombre,
        correo=usuario.correo,
        telefono=usuario.telefono,
        rol=s.RolOut.model_validate(usuario.rol),
        id_empresa=usuario.id_empresa,
        modulos=[s.ModuloOut.model_validate(mod) for mod in modulos],
        proyectos=ids_proyecto,
    )
