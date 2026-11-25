"""Envío de notificaciones Web Push (VAPID) a los navegadores suscritos de cada usuario."""
import json
import logging

from pywebpush import WebPushException, webpush
from starlette.concurrency import run_in_threadpool

from app.core.config import settings
from app.core.database import SessionLocal
from app.models import models as m

logger = logging.getLogger(__name__)


def _url(data: dict | None) -> str:
    d = data or {}
    if d.get("id_pago") or d.get("id_devolucion"):
        return "/dashboard/pagos"
    if d.get("id_separacion"):
        return f"/dashboard/separaciones/{d['id_separacion']}"
    if d.get("id_venta"):
        return f"/dashboard/contratos/venta/{d['id_venta']}"
    return "/dashboard"


def _enviar_sync(notifs: list[dict]) -> None:
    db = SessionLocal()
    try:
        for n in notifs:
            subs = db.query(m.PushSuscripcion).filter(m.PushSuscripcion.id_usuario == n["id_usuario_destino"]).all()
            if not subs:
                continue
            cuerpo = json.dumps({
                "titulo": n.get("titulo"), "mensaje": n.get("mensaje") or "",
                "url": _url(n.get("data")), "tag": f"{n.get('tipo')}-{n.get('id')}",
            })
            for sub in subs:
                try:
                    webpush(
                        subscription_info={"endpoint": sub.endpoint, "keys": {"p256dh": sub.p256dh, "auth": sub.auth}},
                        data=cuerpo,
                        vapid_private_key=settings.VAPID_PRIVATE_KEY,
                        vapid_claims={"sub": settings.VAPID_SUBJECT},
                        ttl=3600,
                    )
                except WebPushException as e:
                    codigo = getattr(e.response, "status_code", None)
                    if codigo in (404, 410):
                        db.delete(sub)  # el navegador ya no existe
                    else:
                        logger.warning("Push falló (%s): %s", codigo, e)
        db.commit()
    finally:
        db.close()


async def enviar_push(notifs: list[dict]) -> None:
    """Nunca rompe la operación principal."""
    if not notifs or not settings.VAPID_PRIVATE_KEY:
        return
    try:
        await run_in_threadpool(_enviar_sync, notifs)
    except Exception:
        logger.exception("No se pudo enviar el push")