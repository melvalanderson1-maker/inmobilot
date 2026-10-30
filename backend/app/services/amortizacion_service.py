"""Amortización a capital en contratos CON interés (más de 24 meses).

Modalidades de pago:
  - adelanto          -> no cambia el cronograma (lo resuelve pagos.py como siempre).
  - amortizar_cuota   -> el cliente abona capital y baja la cuota; mismas fechas y misma cantidad de cuotas.
  - amortizar_plazo   -> el cliente abona capital y mantiene la cuota; el contrato termina antes.

Reglas:
  1. El monto primero paga las cuotas que ya vencieron (completas), luego el interés devengado desde el
     último pago aplicado hasta la fecha del pago (interés compuesto por días reales, igual que
     reglas_venta.calcular_liquidacion). Lo que sobra baja el capital.
  2. Las cuotas ya pagadas y el historial no se tocan. Se recalculan solo las filas con fecha posterior al pago.
  3. Se respeta la frecuencia con la que se creó la venta: mensual / bimestral / trimestral / semestral /
     anual (con detalle mensual) / pago único / personalizada.
"""
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from fastapi import HTTPException

from app.services import reglas_venta as reglas

Q2 = Decimal("0.01")
MODALIDADES_AMORTIZACION = ("amortizar_cuota", "amortizar_plazo")


def _q(x) -> Decimal:
    return Decimal(str(x)).quantize(Q2, rounding=ROUND_HALF_UP)


def _estado(c) -> str:
    e = c.estado
    return getattr(e, "value", e)


def _err(codigo: int, detalle: str):
    raise HTTPException(status_code=codigo, detail=detalle)


def _factor_dias(tea: float, dias: int) -> Decimal:
    return Decimal(str((1 + tea) ** (max(dias, 0) / 365) - 1))


def _factor_meses(tea: float, meses: int) -> Decimal:
    return Decimal(str((1 + tea) ** (meses / 12) - 1))


def _prox_fin_mes(d: date) -> date:
    f = reglas._fin_de_mes(d.year, d.month)
    return f if f > d else reglas._sumar_meses_fin_de_mes(d, 1)


# ---------------------------------------------------------------- situación --

def situacion(contrato, cuotas, fecha_pago: date, previas=None) -> dict:
    """Foto del contrato al momento de amortizar: capital vigente, último pago aplicado y cuotas pendientes."""
    if not contrato.tiene_interes or not contrato.tea or Decimal(str(contrato.tea)) <= 0:
        _err(422, "La amortización a capital solo aplica a contratos con interés")

    filas_pago = sorted((c for c in cuotas if c.requiere_pago), key=lambda c: c.numero_cuota)
    pos = {c.numero_cuota: i + 1 for i, c in enumerate(filas_pago)}  # N° de cuota como lo ve el cliente (1, 2, 3...)
    for c in filas_pago:
        if _estado(c) == "parcial":
            _err(409, f"La cuota {pos[c.numero_cuota]} tiene un pago parcial. Complétala antes de amortizar capital")
    pendientes = [c for c in filas_pago if _estado(c) != "pagada"]
    pagadas = [c for c in filas_pago if _estado(c) == "pagada"]
    if not pendientes:
        _err(409, "No quedan cuotas pendientes")
    if pagadas and pagadas[-1].numero_cuota > pendientes[0].numero_cuota:
        _err(409, "Las cuotas deben estar pagadas en orden antes de amortizar capital")

    if pagadas:
        ultima = pagadas[-1]
        capital = Decimal(str(ultima.capital))
        ancla = ultima.fecha_pago_programada
        acum_base = Decimal(str(ultima.interes_acumulado or 0))
    else:
        capital = Decimal(str(contrato.saldo_financiado))
        ancla = contrato.fecha_inicio_interes or contrato.fecha_abono or contrato.fecha_contrato
        acum_base = Decimal("0")

    # Si ya hubo una amortización posterior al último pago aplicado, el capital vigente es el que dejó esa amortización
    fes_previas = [
        date.fromisoformat(str(d["fecha_efectiva"])[:10]) for d in (previas or []) if d and d.get("fecha_efectiva")
    ]
    if fes_previas and max(fes_previas) > ancla:
        p0 = pendientes[0]
        capital = Decimal(str(p0.capital)) + Decimal(str(p0.amortizacion))
        ancla = max(fes_previas)
        acum_base = Decimal(str(p0.interes_acumulado or 0)) - Decimal(str(p0.interes_mensual or 0))

    fe = max(fecha_pago, ancla)  # fecha efectiva: el interés ya pagado llega hasta el ancla

    # Como en los bancos: las cuotas que ya vencieron (o vencen ese día) se pagan PRIMERO, completas.
    # Lo que sobre del monto, después del interés, es lo que baja el capital.
    cubiertas = [c for c in pendientes if c.fecha_pago_programada <= fe]
    if cubiertas:
        restantes = pendientes[len(cubiertas):]
        if not restantes:
            _err(409, "Todas las cuotas que faltan ya vencieron. Págalas como cuotas normales (Adelantar cuotas) o cancela el contrato")
        ult = cubiertas[-1]
        capital = Decimal(str(ult.capital))
        ancla = ult.fecha_pago_programada
        acum_base = Decimal(str(ult.interes_acumulado or 0))
        fe = max(fecha_pago, ancla)
        pendientes = restantes
    monto_cubiertas = sum((Decimal(str(c.monto_cuota)) for c in cubiertas), Decimal("0"))

    tea_pct = Decimal(str(contrato.tea))
    interes = reglas.calcular_liquidacion(capital, ancla, tea_pct, fe)["interes"]
    return {
        "capital": capital, "ancla": ancla, "fe": fe, "interes": interes, "acum_base": acum_base,
        "pendientes": pendientes, "fechas": [c.fecha_pago_programada for c in pendientes],
        "tea": float(tea_pct / 100),
        "cubiertas": cubiertas, "monto_cubiertas": monto_cubiertas, "pos": pos,
    }


# ------------------------------------------------------------ motor de cuotas --

def _tasas_periodos(contrato, s) -> list[Decimal]:
    """Factor de interés de cada período entre pagos pendientes."""
    meses = reglas.MESES_POR_FRECUENCIA.get(contrato.frecuencia_cuota)
    # mensual..semestral conservan la tasa por período del cronograma original; anual/único/personalizada: días reales
    fijo = meses is not None and contrato.frecuencia_cuota != "anual"
    tasas, previa = [], s["fe"]
    for i, d in enumerate(s["fechas"]):
        if fijo and (i > 0 or s["fe"] == s["ancla"]):
            tasas.append(_factor_meses(s["tea"], meses))
        else:
            tasas.append(_factor_dias(s["tea"], (d - previa).days))
        previa = d
    return tasas


def _simular(K: Decimal, tasas, cuota: Decimal) -> Decimal:
    """Saldo que queda después de pagar `cuota` en todos los períodos (sin liquidar la última)."""
    saldo = K
    for t in tasas:
        saldo -= cuota - _q(saldo * t)
    return saldo


def _cuota_para_reducir(K: Decimal, tasas) -> Decimal:
    producto = Decimal("1")
    for t in tasas:
        producto *= (1 + t)
    bajo, alto = Decimal("0"), K * producto + 1
    for _ in range(80):
        medio = (bajo + alto) / 2
        if _simular(K, tasas, medio) > 0:
            bajo = medio
        else:
            alto = medio
    return alto.quantize(Q2, rounding=ROUND_HALF_UP)


def _pagos_reduciendo_cuota(K: Decimal, tasas) -> list[dict]:
    n = len(tasas)
    cuota = _cuota_para_reducir(K, tasas) if n > 1 else None
    return _recorrer(K, tasas, cuota, n)


def _pagos_reduciendo_plazo(K: Decimal, tasas, cuota_actual: Decimal) -> list[dict]:
    return _recorrer(K, tasas, cuota_actual, len(tasas), liquidar_si_alcanza=True)


def _recorrer(K: Decimal, tasas, cuota: Decimal | None, n: int, liquidar_si_alcanza: bool = False) -> list[dict]:
    saldo, out = K, []
    for i, t in enumerate(tasas):
        interes = _q(saldo * t)
        ultimo = i == n - 1
        if not ultimo and liquidar_si_alcanza and cuota is not None and cuota >= saldo + interes:
            ultimo = True  # con esta cuota ya se cancela todo: el plazo se acorta
        if ultimo or cuota is None:
            amort, monto = saldo, saldo + interes
        else:
            amort, monto = cuota - interes, cuota
            if amort <= 0:
                _err(422, "La cuota actual no alcanza a cubrir el interés del período")
        antes = saldo
        saldo -= amort
        out.append({"i": i, "interes": interes, "amort": amort, "monto": monto, "capital_antes": antes, "capital": saldo})
        if saldo <= 0:
            break
    return out


def _armar_filas(contrato, s, pagos: list[dict]) -> list[dict]:
    """Convierte los pagos calculados en filas del cronograma (con detalle mensual si es anual)."""
    fechas = s["fechas"]
    if contrato.frecuencia_cuota != "anual":
        filas, acum = [], s["acum_base"] + s["interes"]
        for p in pagos:
            acum += p["interes"]
            filas.append({
                "fecha": fechas[p["i"]], "capital": _q(p["capital"]), "amortizacion": _q(p["amort"]),
                "interes": p["interes"], "acumulado": _q(acum), "monto": _q(p["monto"]), "requiere_pago": True,
            })
        return filas

    # anual: una fila por mes (detalle) y una fila de pago por año
    filas, inicio = [], s["fe"]
    for p in pagos:
        fecha_pago = fechas[p["i"]]
        cap, acum_prev, d, guardia = p["capital_antes"], Decimal("0"), _prox_fin_mes(inicio), 0
        while True:
            guardia += 1
            if d > fecha_pago or guardia > 400:
                _err(500, "La fecha de pago del cronograma anual no coincide con un fin de mes")
            acum = _q(cap * _factor_dias(s["tea"], (d - inicio).days))
            if d == fecha_pago:
                filas.append({
                    "fecha": d, "capital": _q(p["capital"]), "amortizacion": _q(p["amort"]),
                    "interes": acum - acum_prev, "acumulado": acum, "monto": _q(p["monto"]), "requiere_pago": True,
                })
                break
            filas.append({
                "fecha": d, "capital": _q(cap), "amortizacion": Decimal("0.00"),
                "interes": acum - acum_prev, "acumulado": acum, "monto": Decimal("0.00"), "requiere_pago": False,
            })
            acum_prev = acum
            d = reglas._sumar_meses_fin_de_mes(d, 1)
        inicio = fecha_pago
    return filas


# ------------------------------------------------------------------- cotizar --

def cotizar(contrato, cuotas, monto, fecha_pago: date, modalidad: str, previas=None) -> dict:
    """Calcula cómo queda el contrato si el cliente paga `monto` a capital. No escribe nada."""
    if modalidad not in MODALIDADES_AMORTIZACION:
        _err(422, "Modalidad no válida: use amortizar_cuota o amortizar_plazo")
    monto = _q(monto)
    s = situacion(contrato, cuotas, fecha_pago, previas)
    minimo = s["monto_cubiertas"] + s["interes"]
    if monto <= minimo:
        if s["cubiertas"]:
            n = [s["pos"][c.numero_cuota] for c in s["cubiertas"]]
            cuotas_txt = f"la cuota {n[0]}" if len(n) == 1 else f"las cuotas {n[0]} a {n[-1]}"
            _err(422, (
                f"El monto (S/ {monto:,.2f}) debe cubrir primero {cuotas_txt} que ya venció "
                f"(S/ {s['monto_cubiertas']:,.2f}) y el interés hasta la fecha de pago (S/ {s['interes']:,.2f}). "
                f"Mínimo S/ {minimo:,.2f}: lo que pases de ahí baja el capital"
            ))
        _err(422, f"El monto (S/ {monto:,.2f}) no cubre el interés devengado (S/ {s['interes']:,.2f}). Para abonar capital paga más que eso")
    a_capital = monto - minimo
    if a_capital >= s["capital"]:
        _err(422, f"Ese monto cancela todo el saldo (S/ {minimo + s['capital']:,.2f}). Usa la opción de cancelar el contrato")
    K = s["capital"] - a_capital

    tasas = _tasas_periodos(contrato, s)
    anteriores = s["pendientes"]
    cuota_ant = Decimal(str(anteriores[0].monto_cuota))
    if modalidad == "amortizar_cuota":
        pagos = _pagos_reduciendo_cuota(K, tasas)
    else:
        pagos = _pagos_reduciendo_plazo(K, tasas, cuota_ant)
    filas = _armar_filas(contrato, s, pagos)
    cola = [c for c in cuotas if c.fecha_pago_programada > s["fe"]]
    for i, f in enumerate(filas):  # N° que verá el cliente (1, 2, 3...) para filas de pago
        fila_db = cola[i] if i < len(cola) else (cola[-1] if cola else None)
        f["numero"] = s["pos"].get(fila_db.numero_cuota, fila_db.numero_cuota) if fila_db else i + 1
    filas_pago = [f for f in filas if f["requiere_pago"]]

    viejo_total = sum((Decimal(str(c.monto_cuota)) for c in anteriores), Decimal("0"))
    interes_viejo = viejo_total - s["capital"]
    interes_nuevo = s["interes"] + sum((f["monto"] for f in filas_pago), Decimal("0")) - K
    return {
        "modalidad": modalidad, "fecha_efectiva": s["fe"], "monto": monto,
        "capital_antes": s["capital"], "interes_devengado": s["interes"], "a_capital": a_capital,
        "capital_despues": K, "cuota_anterior": cuota_ant, "cuota_nueva": filas_pago[0]["monto"],
        "cuotas_antes": len(anteriores), "cuotas_despues": len(filas_pago),
        "ahorro_interes": max(interes_viejo - interes_nuevo, Decimal("0")),
        "monto_cancelacion": s["monto_cubiertas"] + s["capital"] + s["interes"],
        "cuotas_cubiertas": [s["pos"][c.numero_cuota] for c in s["cubiertas"]],
        "monto_cuotas_cubiertas": s["monto_cubiertas"],
        "filas": filas, "cronograma": filas_pago, "_cubiertas": s["cubiertas"],
    }


# ------------------------------------------------------------------- aplicar --

def aplicar_amortizacion(db, m, contrato, pago) -> dict:
    """Se llama cuando Facturación valida el pago: reescribe las filas pendientes del cronograma."""
    cuotas = (
        db.query(m.CronogramaPago)
        .filter(m.CronogramaPago.id_contrato == contrato.id)
        .order_by(m.CronogramaPago.numero_cuota)
        .all()
    )
    previas = [
        p.detalle_amortizacion
        for p in db.query(m.Pago).filter(
            m.Pago.id_contrato == contrato.id, m.Pago.tipo == "amortizacion",
            m.Pago.estado == "validado", m.Pago.id != pago.id,
        ).all()
    ]
    cot = cotizar(contrato, cuotas, pago.monto, pago.fecha_pago, pago.modalidad, previas)
    fe = cot["fecha_efectiva"]
    for c in cot["_cubiertas"]:  # cuotas vencidas que este pago cubre completas
        c.monto_pagado = c.monto_cuota
        c.estado = m.EstadoCuotaEnum.pagada
        c.fecha_pago_real = pago.fecha_pago
    cola = [c for c in cuotas if c.fecha_pago_programada > fe]
    nuevas = cot["filas"]
    ultimo_numero = max((c.numero_cuota for c in cuotas if c.fecha_pago_programada <= fe), default=0)

    for i, f in enumerate(nuevas):
        fila = cola[i] if i < len(cola) else m.CronogramaPago(id_contrato=contrato.id, numero_cuota=ultimo_numero + i + 1)
        if i >= len(cola):
            db.add(fila)
        fila.fecha_pago_programada = f["fecha"]
        fila.capital = f["capital"]
        fila.amortizacion = f["amortizacion"]
        fila.interes_mensual = f["interes"]
        fila.interes_acumulado = f["acumulado"]
        fila.monto_cuota = f["monto"]
        fila.requiere_pago = f["requiere_pago"]
        fila.estado = m.EstadoCuotaEnum.pendiente
        fila.monto_pagado = Decimal("0")
        fila.fecha_pago_real = None

    sobrantes = cola[len(nuevas):]
    if sobrantes:
        ids = [c.id for c in sobrantes]
        db.query(m.Pago).filter(m.Pago.id_cuota.in_(ids)).update({m.Pago.id_cuota: None}, synchronize_session=False)
        for c in sobrantes:
            db.delete(c)

    contrato.numero_cuotas = sum(1 for c in cuotas if c.requiere_pago and c.fecha_pago_programada <= fe) + cot["cuotas_despues"]
    detalle = {
        k: (str(v) if isinstance(v, (Decimal, date)) else v)
        for k, v in cot.items() if k not in ("filas", "cronograma", "_cubiertas")
    }
    pago.detalle_amortizacion = detalle
    return cot