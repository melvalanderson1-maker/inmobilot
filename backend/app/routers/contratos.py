from dateutil.relativedelta import relativedelta
from decimal import Decimal, ROUND_HALF_UP
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload

from app.core.database import get_db
from app.deps import require_modulo, get_ids_proyectos_usuario
from app.models import models as m
from app.schemas import schemas as s
from app.sockets import notificar_cambio_estado_lote, notificar_nuevo_contrato, notificar_pago_registrado

router = APIRouter(prefix="/contratos", tags=["contratos"])

Q2 = Decimal("0.01")


def _validar_acceso_proyecto(db: Session, usuario: m.Usuario, id_proyecto: int):
    ids_permitidos = get_ids_proyectos_usuario(db, usuario)
    if ids_permitidos is not None and id_proyecto not in ids_permitidos:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes acceso a este proyecto")


def _generar_cronograma(contrato: m.Contrato) -> list[m.CronogramaPago]:
    """
    Genera el cronograma de cuotas.

    - Sin interés (o plazo <= 24 meses, regla de negocio): se reparte el saldo
      en partes iguales, con pago en cada cuota según la frecuencia elegida
      (mensual o anual).
    - Con interés y frecuencia mensual: amortización francesa clásica, cuota
      fija cada mes.
    - Con interés y frecuencia anual: el interés se acumula MES A MES (TEM),
      pero el cliente solo paga una vez al año. Las filas intermedias
      (requiere_pago=False) solo muestran el interés acumulado de ese mes;
      la fila de la fecha de pago (requiere_pago=True) es la que salda el
      interés acumulado del periodo + amortiza capital.
    """
    saldo = contrato.saldo_financiado or Decimal("0")
    n = contrato.numero_cuotas or 0
    if n <= 0 or saldo <= 0:
        return []

    fecha_base = contrato.fecha_abono or contrato.fecha_contrato
    frecuencia = contrato.frecuencia_cuota or "mensual"
    meses_por_cuota = 12 if frecuencia == "anual" else 1
    cuotas: list[m.CronogramaPago] = []

    # ---- Sin interés: reparto igual, pago según frecuencia elegida ----
    if not contrato.tiene_interes or not contrato.tem:
        monto_cuota = (saldo / n).quantize(Q2, rounding=ROUND_HALF_UP)
        saldo_restante = saldo
        for i in range(1, n + 1):
            amortizacion = monto_cuota if i < n else saldo_restante
            saldo_restante -= amortizacion
            cuotas.append(
                m.CronogramaPago(
                    numero_cuota=i,
                    fecha_pago_programada=fecha_base + relativedelta(months=i * meses_por_cuota),
                    capital=saldo_restante,
                    amortizacion=amortizacion,
                    interes_mensual=Decimal("0"),
                    interes_acumulado=Decimal("0"),
                    monto_cuota=amortizacion,
                    requiere_pago=True,
                )
            )
        return cuotas

    tem = Decimal(contrato.tem) / Decimal("100")

    # ---- Con interés, frecuencia mensual: francés clásico mes a mes ----
    if frecuencia == "mensual":
        factor = (1 + tem) ** n
        cuota_fija = (saldo * tem * factor) / (factor - 1)
        cuota_fija = cuota_fija.quantize(Q2, rounding=ROUND_HALF_UP)

        saldo_restante = saldo
        interes_acumulado = Decimal("0")
        for i in range(1, n + 1):
            interes_mes = (saldo_restante * tem).quantize(Q2, rounding=ROUND_HALF_UP)
            amortizacion = (cuota_fija - interes_mes).quantize(Q2, rounding=ROUND_HALF_UP)
            if i == n:
                amortizacion = saldo_restante
                cuota_fija_i = amortizacion + interes_mes
            else:
                cuota_fija_i = cuota_fija
            saldo_restante -= amortizacion
            interes_acumulado += interes_mes

            cuotas.append(
                m.CronogramaPago(
                    numero_cuota=i,
                    fecha_pago_programada=fecha_base + relativedelta(months=i),
                    capital=saldo_restante,
                    amortizacion=amortizacion,
                    interes_mensual=interes_mes,
                    interes_acumulado=interes_acumulado,
                    monto_cuota=cuota_fija_i,
                    requiere_pago=True,
                )
            )
        return cuotas

    # ---- Con interés, frecuencia anual: interés mensual acumulado, pago 1 vez al año ----
    tasa_periodo = (1 + tem) ** meses_por_cuota - 1
    factor = (1 + tasa_periodo) ** n
    cuota_fija = (saldo * tasa_periodo * factor) / (factor - 1)
    cuota_fija = cuota_fija.quantize(Q2, rounding=ROUND_HALF_UP)

    saldo_restante = saldo
    numero_fila = 0
    for periodo in range(1, n + 1):
        interes_periodo_acumulado = Decimal("0")
        for mes_en_periodo in range(1, meses_por_cuota + 1):
            numero_fila += 1
            interes_mes = (saldo_restante * tem).quantize(Q2, rounding=ROUND_HALF_UP)
            interes_periodo_acumulado += interes_mes
            fecha_fila = fecha_base + relativedelta(months=numero_fila)
            es_fecha_pago = mes_en_periodo == meses_por_cuota

            if es_fecha_pago:
                if periodo == n:
                    amortizacion = saldo_restante
                    monto_pago = amortizacion + interes_periodo_acumulado
                else:
                    monto_pago = cuota_fija
                    amortizacion = (monto_pago - interes_periodo_acumulado).quantize(Q2, rounding=ROUND_HALF_UP)
                saldo_restante -= amortizacion

                cuotas.append(
                    m.CronogramaPago(
                        numero_cuota=numero_fila,
                        fecha_pago_programada=fecha_fila,
                        capital=saldo_restante,
                        amortizacion=amortizacion,
                        interes_mensual=interes_mes,
                        interes_acumulado=interes_periodo_acumulado,
                        monto_cuota=monto_pago,
                        requiere_pago=True,
                    )
                )
            else:
                cuotas.append(
                    m.CronogramaPago(
                        numero_cuota=numero_fila,
                        fecha_pago_programada=fecha_fila,
                        capital=saldo_restante,
                        amortizacion=Decimal("0"),
                        interes_mensual=interes_mes,
                        interes_acumulado=interes_periodo_acumulado,
                        monto_cuota=Decimal("0"),
                        requiere_pago=False,
                    )
                )

    return cuotas

@router.get("", response_model=list[s.ContratoOut])
def listar_contratos(
    id_proyecto: int,
    usuario: m.Usuario = Depends(require_modulo("contratos")),
    db: Session = Depends(get_db),
):
    _validar_acceso_proyecto(db, usuario, id_proyecto)
    contratos = (
        db.query(m.Contrato)
        .options(
            joinedload(m.Contrato.lote),
            joinedload(m.Contrato.clientes_rel).joinedload(m.ContratoCliente.cliente),
        )
        .filter(m.Contrato.id_proyecto == id_proyecto)
        .order_by(m.Contrato.fecha_contrato.desc())
        .all()
    )
    return [s.ContratoOut.desde_contrato(c) for c in contratos]


@router.get("/{id_contrato}", response_model=s.ContratoOut)
def obtener_contrato(
    id_contrato: int,
    usuario: m.Usuario = Depends(require_modulo("contratos")),
    db: Session = Depends(get_db),
):
    contrato = (
        db.query(m.Contrato)
        .options(
            joinedload(m.Contrato.lote),
            joinedload(m.Contrato.clientes_rel).joinedload(m.ContratoCliente.cliente),
        )
        .filter(m.Contrato.id == id_contrato)
        .first()
    )
    if not contrato:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contrato no encontrado")
    _validar_acceso_proyecto(db, usuario, contrato.id_proyecto)
    return s.ContratoOut.desde_contrato(contrato)


@router.post("", response_model=s.ContratoOut, status_code=status.HTTP_201_CREATED)
async def crear_contrato(
    payload: s.ContratoCreate,
    usuario: m.Usuario = Depends(require_modulo("contratos")),
    db: Session = Depends(get_db),
):
    lote = db.query(m.Lote).filter(m.Lote.id == payload.id_lote).first()
    if not lote:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lote no encontrado")
    _validar_acceso_proyecto(db, usuario, lote.id_proyecto)

    if lote.estado == m.EstadoLoteEnum.vendido:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="El lote ya está vendido")

    existe = (
        db.query(m.Contrato)
        .filter(m.Contrato.id_empresa == usuario.id_empresa, m.Contrato.numero_contrato == payload.numero_contrato)
        .first()
    )
    if existe:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Ya existe un contrato con ese número")

    if not payload.clientes:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Debe indicar al menos un cliente")

    meses_por_cuota_calc = 12 if payload.frecuencia_cuota == "anual" else 1
    plazo_total_meses = payload.numero_cuotas * meses_por_cuota_calc
    tiene_interes_final = payload.tiene_interes and plazo_total_meses > 24

    contrato = m.Contrato(
        numero_contrato=payload.numero_contrato,
        id_lote=lote.id,
        id_proyecto=lote.id_proyecto,
        id_empresa=usuario.id_empresa,
        fecha_contrato=payload.fecha_contrato,
        precio_total=payload.precio_total,
        inicial_abonado=payload.inicial_abonado,
        fecha_abono=payload.fecha_abono,
        tiene_interes=tiene_interes_final,
        forma_pago=payload.forma_pago,
        frecuencia_cuota=payload.frecuencia_cuota,
        saldo_financiado=payload.saldo_financiado,
        numero_cuotas=payload.numero_cuotas,
        tea=payload.tea,
        tcea=payload.tcea,
        tem=payload.tem,
        fecha_inicio_interes=payload.fecha_inicio_interes,
        tipo_contrato=payload.tipo_contrato,
        observaciones=payload.observaciones,
        id_usuario_registro=usuario.id,
    )
    db.add(contrato)
    db.flush()  # para obtener contrato.id sin cerrar la transacción

    # ---- Clientes del contrato (titular, cónyuge, copropietario) ----
    for item in payload.clientes:
        if item.id_cliente:
            cliente = db.query(m.Cliente).filter(m.Cliente.id == item.id_cliente, m.Cliente.id_empresa == usuario.id_empresa).first()
            if not cliente:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Cliente {item.id_cliente} no encontrado")
        elif item.cliente_nuevo:
            cliente = (
                db.query(m.Cliente)
                .filter(m.Cliente.id_empresa == usuario.id_empresa, m.Cliente.numero_documento == item.cliente_nuevo.numero_documento)
                .first()
            )
            if not cliente:
                cliente = m.Cliente(id_empresa=usuario.id_empresa, **item.cliente_nuevo.model_dump())
                db.add(cliente)
                db.flush()
        else:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Cada cliente requiere id_cliente o cliente_nuevo")

        db.add(m.ContratoCliente(id_contrato=contrato.id, id_cliente=cliente.id, rol=item.rol))

    # ---- Cronograma automático ----
    for cuota in _generar_cronograma(contrato):
        cuota.id_contrato = contrato.id
        db.add(cuota)

    # ---- Lote pasa a vendido ----
    estado_anterior = lote.estado
    lote.estado = m.EstadoLoteEnum.vendido
    db.add(
        m.LoteEstadoHistorial(
            id_lote=lote.id,
            estado_anterior=estado_anterior,
            estado_nuevo=m.EstadoLoteEnum.vendido,
            id_usuario=usuario.id,
            observacion=f"Vendido mediante contrato {contrato.numero_contrato}",
        )
    )
    db.add(
        m.Notificacion(
            id_empresa=usuario.id_empresa,
            id_usuario_destino=None,
            tipo="cambio_estado_lote",
            titulo=f"Lote {lote.codigo} vendido",
            mensaje=f"Contrato {contrato.numero_contrato}",
            data={"id_lote": lote.id, "id_proyecto": lote.id_proyecto, "estado": "vendido"},
        )
    )

    db.commit()
    db.refresh(contrato)

    await notificar_cambio_estado_lote(
        s.LoteOut.model_validate(lote).model_dump(mode="json"),
        id_proyecto=lote.id_proyecto,
        id_empresa=usuario.id_empresa,
    )

    contrato_completo = (
        db.query(m.Contrato)
        .options(
            joinedload(m.Contrato.lote),
            joinedload(m.Contrato.clientes_rel).joinedload(m.ContratoCliente.cliente),
        )
        .filter(m.Contrato.id == contrato.id)
        .first()
    )
    contrato_out = s.ContratoOut.desde_contrato(contrato_completo)

    await notificar_nuevo_contrato(
        contrato_out.model_dump(mode="json"),
        id_proyecto=contrato.id_proyecto,
        id_empresa=usuario.id_empresa,
    )

    return contrato_out


@router.get("/{id_contrato}/cronograma", response_model=list[s.CronogramaOut])
def ver_cronograma(
    id_contrato: int,
    usuario: m.Usuario = Depends(require_modulo("contratos")),
    db: Session = Depends(get_db),
):
    contrato = db.query(m.Contrato).filter(m.Contrato.id == id_contrato).first()
    if not contrato:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contrato no encontrado")
    _validar_acceso_proyecto(db, usuario, contrato.id_proyecto)

    return (
        db.query(m.CronogramaPago)
        .filter(m.CronogramaPago.id_contrato == id_contrato)
        .order_by(m.CronogramaPago.numero_cuota.asc())
        .all()
    )



@router.get("/{id_contrato}/pagos", response_model=list[s.PagoOut])
def listar_pagos(
    id_contrato: int,
    usuario: m.Usuario = Depends(require_modulo("contratos")),
    db: Session = Depends(get_db),
):
    contrato = db.query(m.Contrato).filter(m.Contrato.id == id_contrato).first()
    if not contrato:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contrato no encontrado")
    _validar_acceso_proyecto(db, usuario, contrato.id_proyecto)

    return (
        db.query(m.Pago)
        .filter(m.Pago.id_contrato == id_contrato)
        .order_by(m.Pago.fecha_pago.desc())
        .all()
    )


@router.post("/{id_contrato}/pagos", response_model=s.PagoOut, status_code=status.HTTP_201_CREATED)
async def registrar_pago(
    id_contrato: int,
    payload: s.PagoCreate,
    usuario: m.Usuario = Depends(require_modulo("pagos")),
    db: Session = Depends(get_db),
):
    contrato = db.query(m.Contrato).filter(m.Contrato.id == id_contrato).first()
    if not contrato:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contrato no encontrado")
    _validar_acceso_proyecto(db, usuario, contrato.id_proyecto)

    pago = m.Pago(
        id_cuota=payload.id_cuota,
        id_contrato=id_contrato,
        monto=payload.monto,
        fecha_pago=payload.fecha_pago,
        metodo_pago=payload.metodo_pago,
        numero_operacion=payload.numero_operacion,
        comprobante_url=payload.comprobante_url,
        registrado_por=usuario.id,
        observacion=payload.observacion,
    )
    db.add(pago)

    if payload.id_cuota:
        cuota = db.query(m.CronogramaPago).filter(m.CronogramaPago.id == payload.id_cuota).first()
        if cuota:
            cuota.monto_pagado = (cuota.monto_pagado or Decimal("0")) + payload.monto
            if cuota.monto_pagado >= cuota.monto_cuota:
                cuota.estado = m.EstadoCuotaEnum.pagada
                cuota.fecha_pago_real = payload.fecha_pago
            else:
                cuota.estado = m.EstadoCuotaEnum.parcial

    db.commit()
    db.refresh(pago)

    await notificar_pago_registrado(
        id_contrato=id_contrato,
        id_proyecto=contrato.id_proyecto,
        id_empresa=usuario.id_empresa,
    )

    return pago