"""Reglas de negocio de la venta (PDF PROCESO DE VENTA) y cálculo del cronograma."""
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from dateutil.relativedelta import relativedelta
from fastapi import HTTPException

INICIAL_MINIMA = Decimal("10000")
PLAZO_MAX_MESES = 24          # 2 años: 24 cuotas mensuales o 4 semestrales
TEA_DEFECTO = Decimal("20")   # interés anual cuando el plazo supera los 24 meses
MESES_POR_FRECUENCIA = {"mensual": 1, "bimestral": 2, "trimestral": 3, "semestral": 6}
FRECUENCIAS = ("mensual", "bimestral", "trimestral", "semestral", "unico")
Q2 = Decimal("0.01")


def _es_contado(forma_pago) -> bool:
    return getattr(forma_pago, "value", forma_pago) == "contado"


def plazo_meses_de(dc: dict) -> int:
    """Soporta ventas antiguas que guardaban 'plazo_anios'."""
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
        raise HTTPException(status_code=422, detail="La frecuencia debe ser mensual, bimestral, trimestral, semestral o pago único")
    plazo = plazo_meses_de(dc)
    if not (1 <= plazo <= 120):
        raise HTTPException(status_code=422, detail="El plazo debe estar entre 1 y 120 meses")
    if frecuencia != "unico" and plazo % MESES_POR_FRECUENCIA[frecuencia] != 0:
        raise HTTPException(
            status_code=422,
            detail=f"Con pagos {frecuencia}es el plazo debe ser múltiplo de {MESES_POR_FRECUENCIA[frecuencia]} meses",
        )


def evaluar(precio_total, forma_pago, dc: dict | None, lote) -> dict:
    """Devuelve los motivos por los que hace falta autorización y un resumen del financiamiento."""
    precio_total = Decimal(str(precio_total))
    motivos: list[dict] = []
    resumen = {
        "plazo_meses": 0,
        "numero_cuotas": 0,
        "tea_aplicable": Decimal("0"),
        "monto_financiar": Decimal("0"),
        "cuota_estimada": Decimal("0"),
    }

    es_contado = _es_contado(forma_pago)
    minimo = lote.precio_total_contado if es_contado else (lote.precio_total_financiado or lote.precio_total_base)
    if minimo and precio_total < Decimal(str(minimo)):
        motivos.append({
            "codigo": "precio_bajo_minimo",
            "mensaje": f"El precio (S/ {precio_total:,.2f}) es menor al del lote (S/ {Decimal(str(minimo)):,.2f})",
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
        n = numero_cuotas(frecuencia, plazo)
        tea = tea_aplicable(plazo, dc.get("tea_financiamiento"))
        resumen.update({"plazo_meses": plazo, "numero_cuotas": n, "tea_aplicable": tea, "monto_financiar": saldo})
        if saldo > 0 and n > 0:
            filas = generar_cuotas(saldo, n, meses_por_cuota(frecuencia, plazo), tea, date.today())
            resumen["cuota_estimada"] = filas[0]["monto"]

    return {"motivos": motivos, "requiere_autorizacion": bool(motivos), **resumen}