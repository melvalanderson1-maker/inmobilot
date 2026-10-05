"""Lógica de negocio del módulo de ventas: generación de Minuta / Contrato
Preparatorio a partir de plantillas Word (docxtpl) y conversión a PDF con
LibreOffice headless."""
import os
import subprocess
import uuid
from datetime import date
from dateutil.relativedelta import relativedelta

from docxtpl import DocxTemplate
from fastapi import HTTPException, status
from sqlalchemy.orm import Session, joinedload, selectinload

from app.deps import get_ids_proyectos_usuario
from app.core.config import settings
from app.models import models as m

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # backend/app
DIR_PLANTILLAS = os.path.join(_BASE_DIR, "static", "plantillas")
DIR_DOCUMENTOS_VENTA = os.path.join(_BASE_DIR, "static", "documentos_venta")
os.makedirs(DIR_DOCUMENTOS_VENTA, exist_ok=True)

PLANTILLA_POR_FORMA_PAGO = {
    m.FormaPagoEnum.contado: "plantilla_minuta.docx",
    m.FormaPagoEnum.credito: "plantilla_contrato_preparatorio.docx",
}

MESES_ES = {
    1: "ENERO", 2: "FEBRERO", 3: "MARZO", 4: "ABRIL", 5: "MAYO", 6: "JUNIO",
    7: "JULIO", 8: "AGOSTO", 9: "SEPTIEMBRE", 10: "OCTUBRE", 11: "NOVIEMBRE", 12: "DICIEMBRE",
}


# ------------------------------------------------------------- utilidades --

def validar_acceso_proyecto(db: Session, usuario: m.Usuario, id_proyecto: int):
    ids_permitidos = get_ids_proyectos_usuario(db, usuario)
    if ids_permitidos is not None and id_proyecto not in ids_permitidos:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes acceso a este proyecto")


def cargar_venta(db: Session, id_venta: int, usuario: m.Usuario) -> m.Venta:
    venta = (
        db.query(m.Venta)
        .options(
            joinedload(m.Venta.lote),
            selectinload(m.Venta.clientes_rel).joinedload(m.VentaCliente.cliente),
            selectinload(m.Venta.ubicaciones),
        )
        .filter(m.Venta.id == id_venta, m.Venta.id_empresa == usuario.id_empresa)
        .first()
    )
    if not venta:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Venta no encontrada")
    validar_acceso_proyecto(db, usuario, venta.id_proyecto)
    return venta


# --------------------------------------------------- números -> letras ----

_UNIDADES = ["", "UNO", "DOS", "TRES", "CUATRO", "CINCO", "SEIS", "SIETE", "OCHO", "NUEVE"]
_DIEZ_19 = ["DIEZ", "ONCE", "DOCE", "TRECE", "CATORCE", "QUINCE", "DIECISÉIS", "DIECISIETE", "DIECIOCHO", "DIECINUEVE"]
_DECENAS = ["", "", "VEINTE", "TREINTA", "CUARENTA", "CINCUENTA", "SESENTA", "SETENTA", "OCHENTA", "NOVENTA"]
_CENTENAS = ["", "CIENTO", "DOSCIENTOS", "TRESCIENTOS", "CUATROCIENTOS", "QUINIENTOS",
             "SEISCIENTOS", "SETECIENTOS", "OCHOCIENTOS", "NOVECIENTOS"]


def _grupo_a_letras(n: int) -> str:
    if n == 0:
        return ""
    if n == 100:
        return "CIEN"
    c, resto = divmod(n, 100)
    d, u = divmod(resto, 10)
    partes = []
    if c:
        partes.append(_CENTENAS[c])
    if resto:
        if 10 <= resto < 20:
            partes.append(_DIEZ_19[resto - 10])
        elif resto < 10:
            partes.append(_UNIDADES[resto])
        else:
            if u == 0:
                partes.append(_DECENAS[d])
            elif d == 2:
                partes.append("VEINTI" + _UNIDADES[u].lower().upper())
            else:
                partes.append(_DECENAS[d] + " Y " + _UNIDADES[u])
    return " ".join(partes)


def numero_a_letras(valor) -> str:
    """Convierte la parte entera de un monto en soles a letras (mayúsculas)."""
    entero = int(valor)
    if entero == 0:
        return "CERO"
    if entero == 1:
        return "UN"

    millones, resto = divmod(entero, 1_000_000)
    miles, unidades = divmod(resto, 1000)

    partes = []
    if millones:
        partes.append(("UN MILLÓN" if millones == 1 else f"{_grupo_a_letras(millones)} MILLONES"))
    if miles:
        partes.append("MIL" if miles == 1 else f"{_grupo_a_letras(miles)} MIL")
    if unidades:
        partes.append(_grupo_a_letras(unidades))
    return " ".join(partes) if partes else "CERO"


def _lindero_texto(colindante: str | None, medida) -> str:
    if not colindante and not medida:
        return ""
    partes = []
    if colindante:
        partes.append(f"CON {colindante}")
    if medida:
        partes.append(f"CON {medida} ML.")
    return " ".join(partes)


def _fecha_texto(f: date) -> str:
    return f.strftime("%d/%m/%Y")


def _componer_pagos_detalle(pagos_previos: list[dict] | None) -> str:
    if not pagos_previos:
        return ""
    frases = []
    for pago in pagos_previos:
        monto = pago["monto"]
        fecha = date.fromisoformat(pago["fecha"]) if isinstance(pago["fecha"], str) else pago["fecha"]
        frases.append(
            f'LA SUMA DE S/{float(monto):,.2f} ({numero_a_letras(monto)} CON 00/100 SOLES) '
            f'DE FECHA {_fecha_texto(fecha)}'
        )
    return " Y ".join(frases)


# --------------------------------------------- gramática comprador(es) ----

def _nombre_cliente(cliente: m.Cliente) -> str:
    if cliente.tipo_persona == "juridica":
        return cliente.razon_social or cliente.nombres
    return f"{cliente.nombres} {cliente.apellidos}"


def _documento_cliente(cliente: m.Cliente) -> str:
    return cliente.ruc if cliente.tipo_persona == "juridica" else cliente.numero_documento


def construir_contexto_compradores(clientes: list[m.Cliente], modo: str) -> dict:
    """modo: 'preparatorio' (usa "PROMINENTE COMPRADOR") o 'minuta' (usa "COMPRADOR")."""
    bloques = []
    for cli in clientes:
        bloques.append(
            f'{_nombre_cliente(cli)}, IDENTIFICADO CON DNI N° {_documento_cliente(cli)}, '
            f'DE ESTADO CIVIL {(cli.estado_civil or "NO INDICADO").upper()}, '
            f'CON DOMICILIO EN {cli.direccion or "NO INDICADO"}'
        )
    comprador_bloque = " Y ".join(bloques)

    es_plural = len(clientes) > 1
    if modo == "preparatorio":
        denom = "LOS PROMINENTES COMPRADORES" if es_plural else "EL PROMINENTE COMPRADOR"
    else:
        denom = "LOS COMPRADORES" if es_plural else "EL COMPRADOR"

    return {
        "comprador_bloque": comprador_bloque,
        "comprador_denominacion": denom,
        "comprador_quien": "A QUIENES" if es_plural else "A QUIEN",
        "comprador_se_le": "SE LES" if es_plural else "SE LE",
        "comprador_sufijo_plural": "S" if es_plural else "",
    }


# --------------------------------------------------------- generación -----

def generar_documento_venta(db: Session, venta: m.Venta) -> bytes:
    """Rellena la plantilla según forma_pago y devuelve el PDF ya convertido."""
    empresa = db.query(m.Empresa).filter(m.Empresa.id == venta.id_empresa).first()
    lote = venta.lote
    clientes = [vc.cliente for vc in venta.clientes_rel]
    if not clientes:
        raise HTTPException(status_code=422, detail="La venta no tiene compradores registrados")

    nombre_plantilla = PLANTILLA_POR_FORMA_PAGO[venta.forma_pago]
    ruta_plantilla = os.path.join(DIR_PLANTILLAS, nombre_plantilla)
    if not os.path.isfile(ruta_plantilla):
        raise HTTPException(status_code=500, detail=f"No se encontró la plantilla {nombre_plantilla} en el servidor")

    modo = "preparatorio" if venta.forma_pago == m.FormaPagoEnum.credito else "minuta"
    ctx = construir_contexto_compradores(clientes, modo)

    proyecto = db.query(m.Proyecto).filter(m.Proyecto.id == venta.id_proyecto).first()
    proyecto_ubicacion = ""
    if proyecto:
        partes_ubic = [p for p in [proyecto.distrito, proyecto.provincia, proyecto.departamento] if p]
        proyecto_ubicacion = (
            f"EL SECTOR {proyecto.descripcion}, " if proyecto.descripcion else ""
        ) + f"DEL DISTRITO DE {partes_ubic[0] if partes_ubic else ''}" + (
            f", PROVINCIA DE {partes_ubic[1]} Y DEPARTAMENTO DE {partes_ubic[2]}" if len(partes_ubic) >= 3 else ""
        )

    hoy = date.today()
    ctx.update({
        "empresa_razon_social": empresa.nombre_comercial or empresa.razon_social,
        "empresa_ruc": empresa.ruc or "",
        "empresa_representante_nombre": empresa.representante_legal_nombre or "",
        "empresa_representante_dni": empresa.representante_legal_dni or "",
        "empresa_representante_estado_civil": empresa.representante_legal_estado_civil or "",
        "empresa_partida_poderes": empresa.partida_poderes or "",
        "empresa_oficina_registral": empresa.oficina_registral or "",
        "empresa_domicilio": empresa.domicilio_fiscal or "",
        "empresa_cuenta_bancaria": empresa.cuenta_bancaria or "",
        "empresa_banco": empresa.banco or "",
        "ciudad_firma": empresa.ciudad_firma_contratos or "",

        "lote_manzana": lote.manzana_nombre or "",
        "lote_codigo": lote.codigo,
        "lote_area": f"{lote.area_m2}",
        "lote_area_texto": numero_a_letras(lote.area_m2),
        "lote_perimetro": f"{lote.perimetro}" if lote.perimetro else "",
        "lote_partida": lote.partida_registral or "",
        "lote_frente": _lindero_texto(lote.frente_colindante, lote.frente_medida),
        "lote_derecha": _lindero_texto(lote.derecha_colindante, lote.derecha_medida),
        "lote_izquierda": _lindero_texto(lote.izquierda_colindante, lote.izquierda_medida),
        "lote_fondo": _lindero_texto(lote.fondo_colindante, lote.fondo_medida),

        "proyecto_nombre": proyecto.nombre if proyecto else "",
        "proyecto_ubicacion": proyecto_ubicacion,

        "precio_total": f"{venta.precio_total:,.2f}",
        "precio_total_texto": numero_a_letras(venta.precio_total),

        "fecha_firma_numerica": hoy.strftime("%d DE ") + MESES_ES[hoy.month] + hoy.strftime(" DE %Y"),
        "fecha_firma_dia_texto": numero_a_letras(hoy.day),
        "fecha_firma_mes_texto": MESES_ES[hoy.month],
        "fecha_firma_anio_texto": numero_a_letras(hoy.year),

        # Específico de Minuta (contado)
        "pagos_detalle": _componer_pagos_detalle(venta.pagos_previos),

        # Específico de crédito (Contrato Preparatorio)
        "inicial_monto": "", "inicial_monto_texto": "",
        "fecha_deposito": "", "numero_operacion": "",
        "plazo_texto": "", "fecha_maxima_pago": "", "tasa_interes_compensatorio": "",
    })

    if venta.datos_credito:
        dc = venta.datos_credito
        fecha_deposito = date.fromisoformat(dc["fecha_deposito"]) if isinstance(dc["fecha_deposito"], str) else dc["fecha_deposito"]
        plazo_anios = int(dc.get("plazo_anios", 2))
        fecha_maxima = fecha_deposito + relativedelta(years=plazo_anios)
        ctx.update({
            "inicial_monto": f"{float(dc['inicial_monto']):,.2f}",
            "inicial_monto_texto": numero_a_letras(dc["inicial_monto"]),
            "fecha_deposito": _fecha_texto(fecha_deposito),
            "numero_operacion": dc.get("numero_operacion", ""),
            "plazo_texto": f"{numero_a_letras(plazo_anios)} AÑO" + ("S" if plazo_anios != 1 else ""),
            "fecha_maxima_pago": _fecha_texto(fecha_maxima),
            "tasa_interes_compensatorio": f"{dc.get('tasa_interes', 25)}",
        })

    tpl = DocxTemplate(ruta_plantilla)
    tpl.render(ctx)

    nombre_docx = f"venta_{venta.id}_{uuid.uuid4().hex[:8]}.docx"
    ruta_docx = os.path.join(DIR_DOCUMENTOS_VENTA, nombre_docx)
    tpl.save(ruta_docx)

    return _convertir_a_pdf(ruta_docx)


def _convertir_a_pdf(ruta_docx: str) -> bytes:
    carpeta = os.path.dirname(ruta_docx)
    resultado = subprocess.run(
        ["soffice", "--headless", "--convert-to", "pdf", "--outdir", carpeta, ruta_docx],
        capture_output=True, timeout=60,
    )
    if resultado.returncode != 0:
        raise HTTPException(status_code=500, detail=f"Error al convertir a PDF: {resultado.stderr.decode(errors='ignore')}")

    ruta_pdf = ruta_docx.rsplit(".", 1)[0] + ".pdf"
    with open(ruta_pdf, "rb") as f:
        return f.read()


def guardar_documento_pdf(id_venta: int, contenido: bytes) -> str:
    nombre = f"documento_{id_venta}_{uuid.uuid4().hex[:8]}.pdf"
    ruta = os.path.join(DIR_DOCUMENTOS_VENTA, nombre)
    with open(ruta, "wb") as f:
        f.write(contenido)
    ruta_relativa = f"/static/documentos_venta/{nombre}"
    if settings.PUBLIC_URL_BASE:
        return f"{settings.PUBLIC_URL_BASE}{ruta_relativa}"
    return ruta_relativa