"""Reglas de negocio de la venta (PDF PROCESO DE VENTA) y cálculo del cronograma."""
import calendar
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from dateutil.relativedelta import relativedelta
from fastapi import HTTPException

INICIAL_MINIMA = Decimal("10000")
PLAZO_MAX_MESES = 24          # 2 años: 24 cuotas mensuales o 4 semestrales
TEA_DEFECTO = Decimal("20")   # interés anual cuando el plazo supera los 24 meses
MESES_POR_FRECUENCIA = {"mensual": 1, "bimestral": 2, "trimestral": 3, "semestral": 6, "anual": 12}
FRECUENCIAS = ("mensual", "bimestral", "trimestral", "semestral", "anual", "unico", "personalizado")
Q2 = Decimal("0.01")


def _es_contado(forma_pago) -> bool:
    return getattr(forma_pago, "value", forma_pago) == "contado"


def _fecha(valor) -> date:
    return valor if isinstance(valor, date) else date.fromisoformat(str(valor)[:10])


def plazo_meses_de(dc: dict) -> int:
    """Soporta ventas antiguas ('plazo_anios') y cronogramas personalizados
    (el plazo se deduce de la última fecha, redondeando meses hacia arriba)."""
    if dc.get("frecuencia_cuota") == "personalizado" and dc.get("cuotas_personalizadas"):
        base = _fecha(dc["fecha_deposito"]) if dc.get("fecha_deposito") else date.today()
        ultima = max(_fecha(c["fecha"]) for c in dc["cuotas_personalizadas"])
        d = relativedelta(ultima, base)
        return max(d.years * 12 + d.months + (1 if d.days > 0 else 0), 1)
    if dc.get("plazo_meses"):
        return int(dc["plazo_meses"])
    return int(dc.get("plazo_anios", 2)) * 12


def meses_por_cuota(frecuencia: str, plazo_meses: int) -> int:
    return plazo_meses if frecuencia == "unico" else MESES_POR_FRECUENCIA[frecuencia]


def numero_cuotas(frecuencia: str, plazo_meses: int) -> int:
    return 1 if frecuencia == "unico" else plazo_meses // MESES_POR_FRECUENCIA[frecuencia]


def tea_aplicable(plazo_meses: int, tea_indicada) -> Decimal:
    """0% hasta 24 meses; si el plazo es mayor, 20% anual (o la tasa que gerencia haya autorizado)."""
    if plazo_meses <= PLAZO_MAX_MESES:
        return Decimal("0")
    if tea_indicada is None:
        return TEA_DEFECTO
    return Decimal(str(tea_indicada))


def generar_cuotas(saldo, n: int, meses_cuota: int, tea_pct, fecha_base: date) -> list[dict]:
    """Cuotas iguales sin interés, o cuota fija (sistema francés) cuando hay TEA."""
    saldo = Decimal(str(saldo))
    tea_pct = Decimal(str(tea_pct or 0))
    con_interes = tea_pct > 0
    if con_interes:
        r = Decimal(str((1 + float(tea_pct) / 100) ** (meses_cuota / 12) - 1))
        factor = (1 + r) ** n
        cuota_fija = (saldo * r * factor / (factor - 1)).quantize(Q2, rounding=ROUND_HALF_UP)

    filas: list[dict] = []
    restante = saldo
    acumulado = Decimal("0")
    for i in range(1, n + 1):
        if con_interes:
            interes = (restante * r).quantize(Q2, rounding=ROUND_HALF_UP)
            if i == n:
                amort = restante
                monto = amort + interes
            else:
                amort = cuota_fija - interes
                monto = cuota_fija
        else:
            interes = Decimal("0")
            amort = (saldo / n).quantize(Q2, rounding=ROUND_HALF_UP) if i < n else restante
            monto = amort
        restante -= amort
        acumulado += interes
        filas.append({
            "numero": i,
            "fecha": fecha_base + relativedelta(months=i * meses_cuota),
            "capital": restante,
            "amortizacion": amort,
            "interes": interes,
            "acumulado": acumulado,
            "monto": monto,
        })
    return filas


# ----------------------------------------------------------------------------
# Cronograma ANUAL con detalle MENSUAL (método del Excel de Gruselva)
# ----------------------------------------------------------------------------

def _fin_de_mes(anio: int, mes: int) -> date:
    return date(anio, mes, calendar.monthrange(anio, mes)[1])


def _sumar_meses_fin_de_mes(d: date, n: int) -> date:
    t = d.year * 12 + (d.month - 1) + n
    return _fin_de_mes(t // 12, t % 12 + 1)


def _factor_tea(tea: float, dias: int) -> float:
    """(1+TEA)^(dias/365) - 1 : interés compuesto por días reales."""
    return (1 + tea) ** (dias / 365) - 1


def generar_cronograma_anual(saldo, anios: int, tea_pct, fecha_base: date) -> list[dict]:
    """Una fila por MES (siempre, porque la empresa tributa mensualmente) y un pago por AÑO.

    - Las filas vencen a fin de mes. La primera es el primer fin de mes posterior a la fecha base
      (el primer período puede ser parcial: se cobran los días reales).
    - Mes a mes el interés se capitaliza: acumulado = capital * ((1+TEA)^(dias/365) - 1), con días reales.
    - En el aniversario (fin de mes, 12 meses después, 24, 36...) el cliente paga la cuota anual:
      del pago, primero se cubre el interés acumulado y el resto amortiza capital. El acumulado
      vuelve a cero y empieza otro bloque de 12 meses sobre el nuevo capital.
    - Cuota anual fija = anualidad con la TEA. La última cuota liquida capital + interés exactos.
    Cada fila trae requiere_pago (True solo en las fechas de pago)."""
    saldo = Decimal(str(saldo))
    tea = float(Decimal(str(tea_pct or 0)) / 100)
    if anios < 1:
        raise HTTPException(status_code=422, detail="El pago anual requiere un plazo de al menos 12 meses")

    if tea > 0:
        factor = (1 + tea) ** anios
        cuota = (saldo * Decimal(str(tea * factor / (factor - 1)))).quantize(Q2, rounding=ROUND_HALF_UP)
    else:  # sin interés: cuotas anuales iguales
        cuota = (saldo / anios).quantize(Q2, rounding=ROUND_HALF_UP)

    fechas_pago = [_sumar_meses_fin_de_mes(fecha_base, 12 * (k + 1)) for k in range(anios)]
    fecha = _fin_de_mes(fecha_base.year, fecha_base.month)
    if fecha <= fecha_base:
        fecha = _sumar_meses_fin_de_mes(fecha_base, 1)

    filas: list[dict] = []
    capital = saldo                 # capital vigente durante el bloque
    acum_prev = Decimal("0")        # interés acumulado del bloque (mes anterior)
    previa = fecha_base
    k = 0
    primero_del_bloque = True
    while k < anios:
        dias = (fecha - previa).days
        g = _factor_tea(tea, dias)
        if primero_del_bloque:
            acum = (capital * Decimal(str(g))).quantize(Q2, rounding=ROUND_HALF_UP)
        else:
            acum = ((capital + acum_prev) * Decimal(str(g)) + acum_prev).quantize(Q2, rounding=ROUND_HALF_UP)
        interes_mes = acum - acum_prev
        fila = {
            "numero": len(filas) + 1, "fecha": fecha, "capital": capital, "amortizacion": Decimal("0"),
            "interes": interes_mes, "acumulado": acum, "monto": Decimal("0"),
            "requiere_pago": False, "ajustada": False,
        }
        if fecha == fechas_pago[k]:
            if k == anios - 1:
                amort = capital
                monto = capital + acum
                fila["ajustada"] = abs(monto - cuota) > Decimal("0.05")
            else:
                monto = cuota
                amort = monto - acum
            capital = capital - amort
            fila.update({"amortizacion": amort, "monto": monto, "requiere_pago": True, "capital": capital})
            filas.append(fila)
            acum_prev = Decimal("0")
            k += 1
            primero_del_bloque = True
        else:
            filas.append(fila)
            acum_prev = acum
            primero_del_bloque = False
        previa = fecha
        fecha = _sumar_meses_fin_de_mes(fecha, 1)
    return filas


def construir_cronograma(saldo, frecuencia: str, plazo_meses: int, tea_pct, fecha_base: date,
                         cuotas_personalizadas: list[dict] | None = None) -> list[dict]:
    """Punto único de entrada: lo usan la vista previa (evaluar) y la creación del contrato."""
    if frecuencia == "personalizado":
        filas = generar_cuotas_personalizadas(saldo, cuotas_personalizadas or [], tea_pct, fecha_base)
    elif frecuencia == "anual":
        filas = generar_cronograma_anual(saldo, plazo_meses // 12, tea_pct, fecha_base)
    else:
        n = numero_cuotas(frecuencia, plazo_meses)
        filas = generar_cuotas(saldo, n, meses_por_cuota(frecuencia, plazo_meses), tea_pct, fecha_base) if n > 0 else []
    for f in filas:
        f.setdefault("requiere_pago", True)
    return filas


def calcular_liquidacion(capital_base, fecha_base: date, tea_pct, fecha_pago: date) -> dict:
    """Cancelación anticipada: capital pendiente + interés devengado hasta la fecha de pago.
    No se cobran intereses futuros. capital_base es el capital desde fecha_base (último pago aplicado
    o inicio del financiamiento); el interés es compuesto por días reales, igual que el cronograma."""
    capital = Decimal(str(capital_base))
    tea = float(Decimal(str(tea_pct or 0)) / 100)
    dias = max((fecha_pago - fecha_base).days, 0)
    interes = Decimal("0")
    if tea > 0 and capital > 0:
        interes = (capital * Decimal(str(_factor_tea(tea, dias)))).quantize(Q2, rounding=ROUND_HALF_UP)
    return {"capital": capital, "interes": interes, "total": capital + interes, "dias": dias}


def generar_cuotas_personalizadas(saldo, cuotas: list[dict], tea_pct, fecha_base: date) -> list[dict]:
    """Cronograma a medida. Cada cuota trae fecha y, opcionalmente, monto fijo (cuota total).
    Las cuotas sin monto se reparten el saldo restante en partes iguales.
    Interés sobre saldo pendiente, por días reales: saldo * ((1+TEA)^(dias/365) - 1).
    La última cuota liquida el saldo exacto."""
    saldo = Decimal(str(saldo))
    tea = Decimal(str(tea_pct or 0)) / 100
    items = [
        {
            "fecha": _fecha(c["fecha"]),
            "monto": None if c.get("monto") in (None, "") else Decimal(str(c["monto"])),
        }
        for c in cuotas
    ]
    items.sort(key=lambda x: x["fecha"])
    n = len(items)
    if n == 0:
        raise HTTPException(status_code=422, detail="Agrega al menos una cuota al cronograma personalizado")
    n_auto = sum(1 for it in items if it["monto"] is None)

    def interes_de(restante: Decimal, desde: date, hasta: date) -> Decimal:
        if tea <= 0 or restante <= 0:
            return Decimal("0")
        factor = Decimal(str((1 + float(tea)) ** ((hasta - desde).days / 365) - 1))
        return (restante * factor).quantize(Q2, rounding=ROUND_HALF_UP)

    def simular(p_auto: Decimal, liquidar: bool):
        filas: list[dict] = []
        restante = saldo
        previa = fecha_base
        acumulado = Decimal("0")
        for i, it in enumerate(items, 1):
            interes = interes_de(restante, previa, it["fecha"])
            ajustada = False
            if liquidar and i == n:
                amort = restante
                monto = amort + interes
                if it["monto"] is not None and abs(monto - it["monto"]) > Decimal("0.05"):
                    ajustada = True
            else:
                monto = it["monto"] if it["monto"] is not None else p_auto
                amort = monto - interes
            restante -= amort
            acumulado += interes
            filas.append({
                "numero": i, "fecha": it["fecha"], "capital": restante, "amortizacion": amort,
                "interes": interes, "acumulado": acumulado, "monto": monto, "ajustada": ajustada,
            })
            previa = it["fecha"]
        return filas, restante

    p_auto = Decimal("0")
    if n_auto:
        if simular(Decimal("0"), False)[1] <= 0:
            raise HTTPException(
                status_code=422,
                detail="Los montos fijos ya cubren todo el saldo: reduce algún monto o quita montos para que el sistema los calcule",
            )
        anios = max((items[-1]["fecha"] - fecha_base).days / 365, 0)
        alto = saldo * Decimal(str((1 + float(tea)) ** anios)) + 1
        bajo = Decimal("0")
        for _ in range(60):  # búsqueda binaria de la cuota automática
            medio = (bajo + alto) / 2
            if simular(medio, False)[1] > 0:
                bajo = medio
            else:
                alto = medio
        p_auto = alto.quantize(Q2, rounding=ROUND_HALF_UP)

    filas, _ = simular(p_auto, True)
    for f in filas:
        if f["amortizacion"] < 0:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"La cuota {f['numero']} (S/ {f['monto']:,.2f}) no es válida: no cubre el interés del período "
                    f"(S/ {f['interes']:,.2f}) o los montos fijos superan el saldo"
                ),
            )
    return filas


def validar_estructura(forma_pago, precio_total, dc: dict | None) -> None:
    """Errores de datos (422), distintos de las excepciones que se resuelven con autorización."""
    if Decimal(str(precio_total)) <= 0:
        raise HTTPException(status_code=422, detail="El precio total debe ser mayor a cero")
    if _es_contado(forma_pago):
        return
    if not dc:
        raise HTTPException(status_code=422, detail="Completa los datos del crédito (inicial, fecha, operación y plazo)")
    inicial = Decimal(str(dc["inicial_monto"]))
    if inicial <= 0:
        raise HTTPException(status_code=422, detail="La inicial debe ser mayor a cero")
    if inicial > Decimal(str(precio_total)):
        raise HTTPException(status_code=422, detail="La inicial no puede superar el precio total")
    frecuencia = dc.get("frecuencia_cuota", "mensual")
    if frecuencia not in FRECUENCIAS:
        raise HTTPException(status_code=422, detail="La frecuencia debe ser mensual, bimestral, trimestral, semestral, anual, pago único o personalizada")
    if frecuencia == "personalizado":
        cuotas = dc.get("cuotas_personalizadas") or []
        if not cuotas:
            raise HTTPException(status_code=422, detail="Agrega al menos una cuota al cronograma personalizado")
        if len(cuotas) > 60:
            raise HTTPException(status_code=422, detail="El cronograma admite como máximo 60 cuotas")
        anterior = _fecha(dc["fecha_deposito"]) if dc.get("fecha_deposito") else date.today()
        for i, c in enumerate(cuotas, 1):
            f = _fecha(c["fecha"])
            if f <= anterior:
                raise HTTPException(
                    status_code=422,
                    detail=f"La cuota {i} debe tener fecha posterior a " + ("la fecha del depósito" if i == 1 else "la cuota anterior"),
                )
            anterior = f
        plazo_c = plazo_meses_de(dc)
        if not (1 <= plazo_c <= 120):
            raise HTTPException(status_code=422, detail="El cronograma no puede superar los 120 meses")
        return
    plazo = plazo_meses_de(dc)
    if not (1 <= plazo <= 120):
        raise HTTPException(status_code=422, detail="El plazo debe estar entre 1 y 120 meses")
    if frecuencia != "unico" and plazo % MESES_POR_FRECUENCIA[frecuencia] != 0:
        raise HTTPException(
            status_code=422,
            detail=f"Con pagos {frecuencia}es el plazo debe ser múltiplo de {MESES_POR_FRECUENCIA[frecuencia]} meses",
        )


def evaluar(precio_total, forma_pago, dc: dict | None, lote, precio_pactado=None) -> dict:
    """Devuelve los motivos por los que hace falta autorización y un resumen del financiamiento."""
    precio_total = Decimal(str(precio_total))
    motivos: list[dict] = []
    resumen = {
        "plazo_meses": 0,
        "numero_cuotas": 0,
        "tea_aplicable": Decimal("0"),
        "monto_financiar": Decimal("0"),
        "cuota_estimada": Decimal("0"),
        "interes_total": Decimal("0"),
        "cronograma": [],
        "cronograma_mensual": [],
    }

    es_contado = _es_contado(forma_pago)
    if precio_pactado:
        # El precio final acordado en la separación es el que manda
        minimo, origen = precio_pactado, "pactado en la separación"
    else:
        minimo = lote.precio_total_contado if es_contado else (lote.precio_total_financiado or lote.precio_total_base)
        origen = "del lote"
    if minimo and precio_total < Decimal(str(minimo)):
        motivos.append({
            "codigo": "precio_bajo_minimo",
            "mensaje": f"El precio (S/ {precio_total:,.2f}) es menor al {origen} (S/ {Decimal(str(minimo)):,.2f})",
        })

    if not es_contado and dc:
        inicial = Decimal(str(dc["inicial_monto"]))
        plazo = plazo_meses_de(dc)
        frecuencia = dc.get("frecuencia_cuota", "mensual")

        if inicial < INICIAL_MINIMA:
            motivos.append({
                "codigo": "inicial_bajo",
                "mensaje": f"La inicial (S/ {inicial:,.2f}) es menor al mínimo de S/ {INICIAL_MINIMA:,.0f}",
            })
        if plazo > PLAZO_MAX_MESES:
            motivos.append({
                "codigo": "plazo_excedido",
                "mensaje": f"El plazo ({plazo} meses) supera los 24 meses (24 cuotas mensuales o 4 semestrales)",
            })

        saldo = max(precio_total - inicial, Decimal("0"))
        tea = tea_aplicable(plazo, dc.get("tea_financiamiento"))
        fecha_base = _fecha(dc["fecha_deposito"]) if dc.get("fecha_deposito") else date.today()
        filas: list[dict] = []
        if saldo > 0:
            filas = construir_cronograma(saldo, frecuencia, plazo, tea, fecha_base, dc.get("cuotas_personalizadas"))
        filas_pago = [f for f in filas if f.get("requiere_pago", True)]
        cronograma_mensual: list[dict] = []
        if frecuencia == "anual":
            cronograma_mensual = filas  # detalle mes a mes (todas las filas)
            # El cronograma de pagos se muestra con numeración 1..N (cuota 1, 2, 3...)
            filas_pago = [{**f, "numero": i} for i, f in enumerate(filas_pago, 1)]
        resumen.update({
            "plazo_meses": plazo,
            "numero_cuotas": len(filas_pago),
            "tea_aplicable": tea,
            "monto_financiar": saldo,
            "cuota_estimada": filas_pago[0]["monto"] if filas_pago else Decimal("0"),
            "interes_total": sum((f["interes"] for f in filas), Decimal("0")),
            "cronograma": filas_pago,
            "cronograma_mensual": cronograma_mensual,
        })

    return {"motivos": motivos, "requiere_autorizacion": bool(motivos), **resumen}