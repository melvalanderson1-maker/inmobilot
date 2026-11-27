from datetime import date, timedelta
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



ETIQUETAS_ENTIDAD = {
    "pago": "Pago", "separacion": "Separación", "devolucion": "Devolución", "venta": "Venta",
    "cliente": "Cliente", "comprobante": "Comprobante", "contrato": "Contrato",
}

ETIQUETAS_ACCION = {
    "editar": "Editó datos",
    "eliminar": "Eliminó",
    "crear": "Creó",
    "crear_historica": "Creó (carga histórica)",
    "registrar_pago": "Registró un pago",
    "validar_caja": "Caja validó el voucher",
    "rechazar_caja": "Caja rechazó",
    "rechazar_facturacion": "Facturación rechazó",
    "facturar": "Facturación subió el comprobante",
    "corregir_comprobante": "Corrigió el comprobante",
    "corregir_rechazo": "Corrigió tras un rechazo",
    "corregir_nota_credito": "Corrigió la nota de crédito",
    "corregir_voucher": "Caja corrigió el voucher",
    "editar_comprobante": "Editó el comprobante",
    "revertir_validacion_caja": "Caja revirtió su validación",
    "revertir_ejecucion": "Caja revirtió la devolución",
    "solicitar_devolucion": "Solicitó una devolución",
    "resolver_devolucion": "Resolvió la devolución",
    "ejecutar_caja": "Caja ejecutó la devolución",
    "emitir_nota_credito": "Facturación emitió la nota de crédito",
    "convertir": "Convirtió en compra",
    "convertir_historica": "Convirtió en compra (histórica)",
    "liberar_lote": "Liberó el lote",
    "desistir": "Desistió de la venta",
    "recalcular_cuotas": "Recalculó las cuotas",
    "cancelar_contrato": "Canceló el contrato",
    "finalizar_venta": "Finalizó la venta",
}


def _exigir_auditoria(usuario: m.Usuario) -> None:
    if usuario.rol.clave not in ("admin", "gerencia"):
        raise HTTPException(status_code=403, detail="Solo admin o gerencia pueden ver la auditoría")


@router.get("/opciones")
def opciones_auditoria(
    usuario: m.Usuario = Depends(require_permiso("ver_auditoria")),
    db: Session = Depends(get_db),
):
    """Listas para los filtros de la pantalla."""
    _exigir_auditoria(usuario)
    usuarios = (
        db.query(m.Usuario.id, m.Usuario.nombre)
        .filter(m.Usuario.id_empresa == usuario.id_empresa)
        .order_by(m.Usuario.nombre)
        .all()
    )
    return {
        "usuarios": [{"id": i, "nombre": n} for i, n in usuarios],
        "entidades": [{"valor": k, "etiqueta": v} for k, v in ETIQUETAS_ENTIDAD.items()],
        "acciones": [{"valor": k, "etiqueta": v} for k, v in ETIQUETAS_ACCION.items()],
    }


@router.get("/buscar")
def buscar_auditoria(
    entidad: Optional[str] = None,
    accion: Optional[str] = None,
    id_usuario: Optional[int] = None,
    id_entidad: Optional[int] = None,
    desde: Optional[date] = None,
    hasta: Optional[date] = None,
    pagina: int = 1,
    por_pagina: int = 50,
    usuario: m.Usuario = Depends(require_permiso("ver_auditoria")),
    db: Session = Depends(get_db),
):
    """Auditoría con filtros y paginación: quién, qué, cuándo y el antes/después."""
    _exigir_auditoria(usuario)
    q = (
        db.query(m.Auditoria)
        .options(joinedload(m.Auditoria.usuario))
        .filter(m.Auditoria.id_empresa == usuario.id_empresa)
    )
    if entidad:
        q = q.filter(m.Auditoria.entidad == entidad)
    if accion:
        q = q.filter(m.Auditoria.accion == accion)
    if id_usuario:
        q = q.filter(m.Auditoria.id_usuario == id_usuario)
    if id_entidad is not None:
        q = q.filter(m.Auditoria.id_entidad == id_entidad)
    if desde:
        q = q.filter(m.Auditoria.created_at >= desde)
    if hasta:
        q = q.filter(m.Auditoria.created_at < hasta + timedelta(days=1))

    total = q.count()
    por_pagina = max(1, min(por_pagina, 200))
    pagina = max(1, pagina)
    filas = (
        q.order_by(m.Auditoria.created_at.desc(), m.Auditoria.id.desc())
        .offset((pagina - 1) * por_pagina)
        .limit(por_pagina)
        .all()
    )

    # N° de contrato de los pagos (el id del contrato viaja dentro de `cambios`)
    ids_contrato = {
        f.cambios.get("id_contrato")
        for f in filas
        if f.entidad == "pago" and isinstance(f.cambios, dict) and f.cambios.get("id_contrato")
    }
    contratos = (
        dict(db.query(m.Contrato.id, m.Contrato.numero_contrato).filter(m.Contrato.id.in_(ids_contrato)).all())
        if ids_contrato else {}
    )

    def referencia(f: m.Auditoria) -> str:
        c = f.cambios if isinstance(f.cambios, dict) else {}
        if f.entidad == "pago":
            num = contratos.get(c.get("id_contrato"))
            return f"Pago #{f.id_entidad}" + (f" · contrato {num}" if num else "")
        if f.entidad == "devolucion":
            return f"Devolución #{f.id_entidad}" + (f" · separación #{c['id_separacion']}" if c.get("id_separacion") else "")
        return f"{ETIQUETAS_ENTIDAD.get(f.entidad, f.entidad.capitalize())} #{f.id_entidad}"

    return {
        "total": total,
        "pagina": pagina,
        "por_pagina": por_pagina,
        "items": [
            {
                "id": f.id,
                "fecha": f.created_at.isoformat() if f.created_at else None,
                "usuario": f.usuario.nombre if f.usuario else None,
                "entidad": f.entidad,
                "id_entidad": f.id_entidad,
                "referencia": referencia(f),
                "accion": f.accion,
                "accion_texto": ETIQUETAS_ACCION.get(f.accion, f.accion.replace("_", " ").capitalize()),
                "cambios": f.cambios,
            }
            for f in filas
        ],
    }