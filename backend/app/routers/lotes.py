from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload

from app.core.database import get_db
from app.deps import require_modulo, get_ids_proyectos_usuario
from app.models import models as m
from app.schemas import schemas as s
from app.sockets import notificar_nuevo_lote, notificar_cambio_estado_lote, notificar_actualizacion_lote

router = APIRouter(prefix="/lotes", tags=["lotes"])


def _validar_acceso_proyecto(db: Session, usuario: m.Usuario, id_proyecto: int):
    ids_permitidos = get_ids_proyectos_usuario(db, usuario)
    if ids_permitidos is not None and id_proyecto not in ids_permitidos:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes acceso a este proyecto")


@router.get("", response_model=list[s.LoteOut])
def listar_lotes(
    id_proyecto: int,
    usuario: m.Usuario = Depends(require_modulo("lotes")),
    db: Session = Depends(get_db),
):
    _validar_acceso_proyecto(db, usuario, id_proyecto)

    return (
        db.query(m.Lote)
        .options(joinedload(m.Lote.imagenes))
        .filter(m.Lote.id_proyecto == id_proyecto)
        .order_by(m.Lote.codigo.asc())
        .all()
    )


@router.get("/{id_lote}", response_model=s.LoteOut)
def obtener_lote(
    id_lote: int,
    usuario: m.Usuario = Depends(require_modulo("lotes")),
    db: Session = Depends(get_db),
):
    lote = db.query(m.Lote).options(joinedload(m.Lote.imagenes)).filter(m.Lote.id == id_lote).first()
    if not lote:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lote no encontrado")
    _validar_acceso_proyecto(db, usuario, lote.id_proyecto)
    return lote


@router.post("", response_model=s.LoteOut, status_code=status.HTTP_201_CREATED)
async def crear_lote(
    payload: s.LoteCreate,
    usuario: m.Usuario = Depends(require_modulo("lotes")),
    db: Session = Depends(get_db),
):
    _validar_acceso_proyecto(db, usuario, payload.id_proyecto)

    existe = (
        db.query(m.Lote)
        .filter(m.Lote.id_proyecto == payload.id_proyecto, m.Lote.codigo == payload.codigo)
        .first()
    )
    if existe:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Ya existe un lote con ese código en el proyecto")

    lote = m.Lote(**payload.model_dump())
    db.add(lote)
    db.commit()
    db.refresh(lote)

    historial = m.LoteEstadoHistorial(
        id_lote=lote.id,
        estado_anterior=None,
        estado_nuevo=lote.estado,
        id_usuario=usuario.id,
        observacion="Registro inicial del lote",
    )
    db.add(historial)

    notif = m.Notificacion(
        id_empresa=usuario.id_empresa,
        id_usuario_destino=None,
        tipo="nuevo_lote",
        titulo="Nuevo lote registrado",
        mensaje=f"Se registró el lote {lote.codigo}",
        data={"id_lote": lote.id, "id_proyecto": lote.id_proyecto},
    )
    db.add(notif)
    db.commit()
    db.refresh(lote)

    await notificar_nuevo_lote(
        s.LoteOut.model_validate(lote).model_dump(mode="json"),
        id_proyecto=lote.id_proyecto,
        id_empresa=usuario.id_empresa,
    )

    return lote


@router.patch("/{id_lote}", response_model=s.LoteOut)
async def actualizar_lote(
    id_lote: int,
    payload: s.LoteUpdate,
    usuario: m.Usuario = Depends(require_modulo("lotes")),
    db: Session = Depends(get_db),
):
    lote = db.query(m.Lote).filter(m.Lote.id == id_lote).first()
    if not lote:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lote no encontrado")
    _validar_acceso_proyecto(db, usuario, lote.id_proyecto)

    for campo, valor in payload.model_dump(exclude_unset=True).items():
        setattr(lote, campo, valor)

    db.commit()
    db.refresh(lote)

    lote_completo = db.query(m.Lote).options(joinedload(m.Lote.imagenes)).filter(m.Lote.id == lote.id).first()
    await notificar_actualizacion_lote(
        s.LoteOut.model_validate(lote_completo).model_dump(mode="json"),
        id_proyecto=lote.id_proyecto,
        id_empresa=usuario.id_empresa,
    )

    return lote_completo


@router.patch("/{id_lote}/estado", response_model=s.LoteOut)
async def cambiar_estado_lote(
    id_lote: int,
    payload: s.LoteEstadoUpdate,
    usuario: m.Usuario = Depends(require_modulo("lotes")),
    db: Session = Depends(get_db),
):
    lote = db.query(m.Lote).filter(m.Lote.id == id_lote).first()
    if not lote:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lote no encontrado")
    _validar_acceso_proyecto(db, usuario, lote.id_proyecto)

    estado_anterior = lote.estado
    lote.estado = payload.estado

    historial = m.LoteEstadoHistorial(
        id_lote=lote.id,
        estado_anterior=estado_anterior,
        estado_nuevo=payload.estado,
        id_usuario=usuario.id,
        observacion=payload.observacion,
    )
    db.add(historial)

    notif = m.Notificacion(
        id_empresa=usuario.id_empresa,
        id_usuario_destino=None,
        tipo="cambio_estado_lote",
        titulo=f"Lote {lote.codigo} cambió a {payload.estado.value}",
        mensaje=payload.observacion,
        data={"id_lote": lote.id, "id_proyecto": lote.id_proyecto, "estado": payload.estado.value},
    )
    db.add(notif)

    db.commit()
    db.refresh(lote)

    await notificar_cambio_estado_lote(
        s.LoteOut.model_validate(lote).model_dump(mode="json"),
        id_proyecto=lote.id_proyecto,
        id_empresa=usuario.id_empresa,
    )

    return lote

@router.post("/{id_lote}/imagenes", response_model=s.LoteImagenOut, status_code=status.HTTP_201_CREATED)
async def agregar_imagen_lote(
    id_lote: int,
    payload: s.LoteImagenCreate,
    usuario: m.Usuario = Depends(require_modulo("lotes")),
    db: Session = Depends(get_db),
):
    lote = db.query(m.Lote).filter(m.Lote.id == id_lote).first()
    if not lote:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lote no encontrado")
    _validar_acceso_proyecto(db, usuario, lote.id_proyecto)

    imagen = m.LoteImagen(
        id_lote=id_lote,
        url=payload.url,
        es_portada=payload.es_portada,
        orden=payload.orden,
    )
    db.add(imagen)
    db.commit()
    db.refresh(imagen)

    lote_completo = db.query(m.Lote).options(joinedload(m.Lote.imagenes)).filter(m.Lote.id == id_lote).first()
    await notificar_actualizacion_lote(
        s.LoteOut.model_validate(lote_completo).model_dump(mode="json"),
        id_proyecto=lote.id_proyecto,
        id_empresa=usuario.id_empresa,
    )

    return imagen


@router.delete("/{id_lote}/imagenes/{id_imagen}", status_code=status.HTTP_204_NO_CONTENT)
async def eliminar_imagen_lote(
    id_lote: int,
    id_imagen: int,
    usuario: m.Usuario = Depends(require_modulo("lotes")),
    db: Session = Depends(get_db),
):
    lote = db.query(m.Lote).filter(m.Lote.id == id_lote).first()
    if not lote:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lote no encontrado")
    _validar_acceso_proyecto(db, usuario, lote.id_proyecto)

    imagen = db.query(m.LoteImagen).filter(m.LoteImagen.id == id_imagen, m.LoteImagen.id_lote == id_lote).first()
    if not imagen:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Imagen no encontrada")

    db.delete(imagen)
    db.commit()

    lote_completo = db.query(m.Lote).options(joinedload(m.Lote.imagenes)).filter(m.Lote.id == id_lote).first()
    await notificar_actualizacion_lote(
        s.LoteOut.model_validate(lote_completo).model_dump(mode="json"),
        id_proyecto=lote.id_proyecto,
        id_empresa=usuario.id_empresa,
    )