"""
Nexus - capa de tiempo real basada en Socket.io.

Eventos que emitimos:
- "lote:nuevo"            -> cuando se registra un lote nuevo
- "lote:cambio_estado"    -> cuando un lote cambia de estado
- "lead:nuevo"            -> cuando se captura un lead desde el sitio público
- "cuota:vence_hoy"       -> cuando el job diario detecta cuotas que vencen hoy
- "notificacion:nueva"    -> evento genérico, siempre acompaña a los anteriores

Salas (rooms) usadas:
- f"empresa:{id_empresa}"   -> todos los usuarios logueados de una empresa
- f"proyecto:{id_proyecto}" -> usuarios con acceso a ese proyecto específico
- f"usuario:{id_usuario}"   -> canal privado de un usuario (sus notificaciones)
"""

import socketio

from app.core.security import decode_access_token

sio = socketio.AsyncServer(
    async_mode="asgi",
    cors_allowed_origins="*",  # ajustar en producción a settings.cors_origins_list
)

socket_app = socketio.ASGIApp(sio, socketio_path="socket.io")


@sio.event
async def connect(sid, environ, auth):
    """El admin conecta con { auth: { token: '<jwt>' } }. El sitio público conecta
    sin token y se une a la sala de su proyecto vía 'unirse_proyecto_publico'."""
    token = (auth or {}).get("token") if auth else None
    if not token:
        await sio.save_session(sid, {"user_id": None, "id_empresa": None})
        return True

    payload = decode_access_token(token)
    if payload is None:
        return False

    user_id = payload.get("sub")
    id_empresa = payload.get("id_empresa")
    proyectos = payload.get("proyectos", [])

    await sio.save_session(sid, {"user_id": user_id, "id_empresa": id_empresa})

    if user_id:
        await sio.enter_room(sid, f"usuario:{user_id}")
    if id_empresa:
        await sio.enter_room(sid, f"empresa:{id_empresa}")
    for id_proyecto in proyectos:
        await sio.enter_room(sid, f"proyecto:{id_proyecto}")

    return True


@sio.event
async def unirse_proyecto_publico(sid, data):
    """El catálogo público llama esto tras conectar, para recibir cambios de estado de lotes."""
    id_proyecto = (data or {}).get("id_proyecto")
    if id_proyecto:
        await sio.enter_room(sid, f"proyecto:{id_proyecto}")

@sio.event
async def disconnect(sid):
    pass


# ------------------------------------------------------------------ helpers


async def emitir_evento(evento: str, data: dict, room: str):
    await sio.emit(evento, data, room=room)


async def notificar_nuevo_lote(lote_dict: dict, id_proyecto: int, id_empresa: int):
    await emitir_evento("lote:nuevo", lote_dict, room=f"proyecto:{id_proyecto}")
    await emitir_evento("notificacion:nueva", lote_dict, room=f"empresa:{id_empresa}")


async def notificar_cambio_estado_lote(lote_dict: dict, id_proyecto: int, id_empresa: int):
    await emitir_evento("lote:cambio_estado", lote_dict, room=f"proyecto:{id_proyecto}")
    await emitir_evento("notificacion:nueva", lote_dict, room=f"empresa:{id_empresa}")


async def notificar_nuevo_lead(lead_dict: dict, id_proyecto: int, id_empresa: int, id_usuario_destino: int | None):
    await emitir_evento("lead:nuevo", lead_dict, room=f"proyecto:{id_proyecto}")
    await emitir_evento("notificacion:nueva", lead_dict, room=f"empresa:{id_empresa}")


async def notificar_cuota_vence_hoy(cuota_dict: dict, id_usuario_destino: int, id_empresa: int):
    room = f"usuario:{id_usuario_destino}" if id_usuario_destino else f"empresa:{id_empresa}"
    await emitir_evento("cuota:vence_hoy", cuota_dict, room=room)
    await emitir_evento("notificacion:nueva", cuota_dict, room=room)


async def notificar_actualizacion_proyectos(id_usuario: int):
    await emitir_evento("usuario:proyectos_actualizados", {"id_usuario": id_usuario}, room=f"usuario:{id_usuario}")


async def notificar_actualizacion_lote(lote_dict: dict, id_proyecto: int, id_empresa: int):
    await emitir_evento("lote:actualizado", lote_dict, room=f"proyecto:{id_proyecto}")
    await emitir_evento("notificacion:nueva", lote_dict, room=f"empresa:{id_empresa}")


async def notificar_nuevo_contrato(contrato_dict: dict, id_proyecto: int, id_empresa: int):
    await emitir_evento("contrato:nuevo", contrato_dict, room=f"proyecto:{id_proyecto}")
    await emitir_evento("notificacion:nueva", contrato_dict, room=f"empresa:{id_empresa}")


async def notificar_pago_registrado(id_contrato: int, id_proyecto: int, id_empresa: int):
    await emitir_evento("contrato:pago_registrado", {"id_contrato": id_contrato}, room=f"proyecto:{id_proyecto}")
    await emitir_evento("notificacion:nueva", {"id_contrato": id_contrato}, room=f"empresa:{id_empresa}")