"""Lógica de negocio del módulo de ventas: generación de Minuta / Contrato
Preparatorio a partir de plantillas Word (docxtpl) y conversión a PDF con
LibreOffice headless."""
import io
import logging
import os
import re
import subprocess
import uuid
from datetime import date
from urllib.parse import unquote, urlparse
from dateutil.relativedelta import relativedelta

from docx.shared import Mm
from docxtpl import DocxTemplate, InlineImage
from fastapi import HTTPException, status
from sqlalchemy.orm import Session, joinedload, selectinload

from app.deps import get_ids_proyectos_usuario
from app.core.config import settings
from app.models import models as m
from app.services import reglas_venta as reglas
from decimal import Decimal, ROUND_HALF_UP

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # backend/app
DIR_PLANTILLAS = os.path.join(_BASE_DIR, "plantillas")
DIR_DOCUMENTOS_VENTA = os.path.join(_BASE_DIR, "static", "documentos_venta")
os.makedirs(DIR_DOCUMENTOS_VENTA, exist_ok=True)
logger = logging.getLogger(__name__)

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

_EC_MASC_FEM = {
    "SOLTERO": "SOLTERA", "CASADO": "CASADA", "VIUDO": "VIUDA",
    "DIVORCIADO": "DIVORCIADA", "SEPARADO": "SEPARADA",
}
_EC_FEM_MASC = {v: k for k, v in _EC_MASC_FEM.items()}


def _es_mujer_valor(valor) -> bool:
    """'F', 'f', 'Femenino', 'mujer'... -> True. Cualquier otro valor o vacío -> False (masculino)."""
    return str(valor or "").strip().upper()[:1] == "F"


def _es_mujer(cliente: m.Cliente) -> bool:
    """Persona jurídica = femenino ("LA EMPRESA"). Persona natural: campo sexo/genero del cliente."""
    if cliente.tipo_persona == "juridica":
        return True
    return _es_mujer_valor(getattr(cliente, "sexo", None) or getattr(cliente, "genero", None))


def _estado_civil_segun_genero(valor, mujer: bool) -> str:
    ec = (valor or "").strip().upper()
    if not ec:
        return "NO INDICADO"
    base = re.split(r"[\s(/]", ec, maxsplit=1)[0]
    if mujer and base in _EC_MASC_FEM:
        return _EC_MASC_FEM[base]
    if not mujer and base in _EC_FEM_MASC:
        return _EC_FEM_MASC[base]
    return base if base in _EC_MASC_FEM or base in _EC_FEM_MASC else ec


def _nombre_cliente(cliente: m.Cliente) -> str:
    if cliente.tipo_persona == "juridica":
        return cliente.razon_social or cliente.nombres
    return f"{cliente.nombres} {cliente.apellidos}"


def _documento_cliente(cliente: m.Cliente) -> str:
    return cliente.ruc if cliente.tipo_persona == "juridica" else cliente.numero_documento


def construir_contexto_compradores(clientes: list[m.Cliente], modo: str) -> dict:
    """modo: 'preparatorio' (usa "PROMINENTE COMPRADOR") o 'minuta' (usa "COMPRADOR").

    Concordancia automática:
      - 1 comprador  -> singular; varios -> plural.
      - Singular: según su sexo. Plural: femenino solo si TODOS son mujeres; si hay un hombre, masculino.
    """
    mujeres = [_es_mujer(c) for c in clientes]
    es_plural = len(clientes) > 1
    fem = all(mujeres)

    bloques = []
    for cli, mujer in zip(clientes, mujeres):
        juridica = cli.tipo_persona == "juridica"
        partes = [
            _nombre_cliente(cli),
            f'{"IDENTIFICADA" if mujer else "IDENTIFICADO"} CON {"RUC" if juridica else "DNI"} N° {_documento_cliente(cli)}',
        ]
        if not juridica:
            partes.append(f"DE ESTADO CIVIL {_estado_civil_segun_genero(cli.estado_civil, mujer)}")
        partes.append(f'CON DOMICILIO EN {cli.direccion or "NO INDICADO"}')
        bloques.append(", ".join(partes))
    comprador_bloque = bloques[0] if len(bloques) == 1 else "; ".join(bloques[:-1]) + " Y " + bloques[-1]

    articulo = ("LAS" if fem else "LOS") if es_plural else ("LA" if fem else "EL")
    comprador = {
        (False, False): "COMPRADOR", (True, False): "COMPRADORA",
        (False, True): "COMPRADORES", (True, True): "COMPRADORAS",
    }[(fem, es_plural)]
    prominente = ("PROMINENTES " if es_plural else "PROMINENTE ") if modo == "preparatorio" else ""
    este_ultimo = {
        (False, False): "ESTE ÚLTIMO", (True, False): "ESTA ÚLTIMA",
        (False, True): "ESTOS ÚLTIMOS", (True, True): "ESTAS ÚLTIMAS",
    }[(fem, es_plural)]

    return {
        "comprador_bloque": comprador_bloque,
        "comprador_denominacion": f"{articulo} {prominente}{comprador}",
        "comprador_quien": "A QUIENES" if es_plural else "A QUIEN",
        "comprador_se_le": "SE LES" if es_plural else "SE LE",
        "comprador_sufijo_plural": "S" if es_plural else "",
        "comprador_n": "N" if es_plural else "",                       # DECLARA / DECLARAN
        "comprador_adj": ("AS" if es_plural else "A") if fem else ("OS" if es_plural else "O"),  # INTERESADO/A/OS/AS
        "comprador_este_ultimo": este_ultimo,
        "comprador_rol_firma": "COMPRADORA" if fem else "COMPRADOR",
    }


# --------------------------------------- quién firma por la empresa ----

FIRMANTES = ("gerente", "apoderado")


def datos_firmante(empresa: m.Empresa, firmante: str) -> dict:
    """Datos de quien comparece por la empresa. 'gerente' usa las columnas actuales; 'apoderado' las apoderado_*."""
    if firmante not in FIRMANTES:
        raise HTTPException(status_code=422, detail="Firmante no válido: use 'gerente' o 'apoderado'")
    if firmante == "apoderado":
        if not (getattr(empresa, "apoderado_nombre", None) and getattr(empresa, "apoderado_dni", None)):
            raise HTTPException(
                status_code=422,
                detail="La empresa no tiene un apoderado registrado (nombre y DNI). Complete sus datos o firme el gerente general.",
            )
        return {
            "nombre": empresa.apoderado_nombre,
            "dni": empresa.apoderado_dni,
            "genero": getattr(empresa, "apoderado_genero", None),
            "estado_civil": getattr(empresa, "apoderado_estado_civil", None),
            "ocupacion": getattr(empresa, "apoderado_ocupacion", None),
            "domicilio": getattr(empresa, "apoderado_domicilio", None),
            "partida_poderes": getattr(empresa, "apoderado_partida_poderes", None),
        }
    return {
        "nombre": empresa.representante_legal_nombre or "",
        "dni": empresa.representante_legal_dni or "",
        "genero": getattr(empresa, "representante_legal_genero", None),
        "estado_civil": empresa.representante_legal_estado_civil,
        "ocupacion": getattr(empresa, "representante_legal_ocupacion", None) or "EMPRESARIO",
        "domicilio": getattr(empresa, "representante_legal_domicilio", None),
        "partida_poderes": empresa.partida_poderes,
    }


def construir_bloque_representante(documento: str, firmante: str, rep: dict, empresa: m.Empresa) -> str:
    """Texto con el que la empresa comparece. documento: 'contrato' | 'minuta'."""
    mujer = _es_mujer_valor(rep["genero"])
    ident = "IDENTIFICADA" if mujer else "IDENTIFICADO"
    cargo = "SU GERENTE GENERAL" if firmante == "gerente" else ("SU APODERADA" if mujer else "SU APODERADO")
    nombre, dni = rep["nombre"], rep["dni"]
    partida = (rep.get("partida_poderes") or "").strip()
    oficina = empresa.oficina_registral or ""

    if documento == "contrato":
        if firmante == "gerente":
            txt = (
                f"{cargo} {nombre}, {ident} CON DNI N° {dni}, "
                f"FACULTADO SEGÚN PODERES INSCRITOS EN LA PARTIDA N° {partida} "
                f"DEL REGISTRO DE PERSONAS JURÍDICAS DE LA OFICINA REGISTRAL DE {oficina}, "
                f"CON DOMICILIO EN {empresa.domicilio_fiscal or ''}"
            )
        else:  # el modelo del apoderado no cita partida de poderes
            txt = f"{cargo} {nombre}, {ident} CON DNI N° {dni}, CON DOMICILIO EN {empresa.domicilio_fiscal or ''}"
    else:
        partes = [f"{cargo} {nombre}", f"{ident} CON DOCUMENTO NACIONAL DE IDENTIDAD NÚMERO {dni}"]
        if rep.get("estado_civil"):
            partes.append(f"DE ESTADO CIVIL {_estado_civil_segun_genero(rep['estado_civil'], mujer)}")
        if rep.get("ocupacion"):
            partes.append(f"DE OCUPACIÓN {rep['ocupacion']}")
        if rep.get("domicilio"):
            partes.append(f"CON DOMICILIO EN {rep['domicilio']}")
        if partida:
            partes.append(
                f"CUYAS FACULTADES CONSTAN INSCRITAS EN LA PARTIDA N° {partida} "
                f"DEL REGISTRO DE PERSONAS JURÍDICAS DE LA OFICINA REGISTRAL DE {oficina}"
            )
        txt = ", ".join(partes)
    return txt.upper()


# ------------------------------------------------- firmas y vouchers ----

def _ruta_local_de_url(url: str | None) -> str | None:
    """URL pública de un archivo subido (/static/...) -> ruta en disco. Solo dentro de app/static."""
    if not url:
        return None
    ruta_url = unquote(urlparse(url).path)
    if not ruta_url.startswith("/static/"):
        return None
    base = os.path.realpath(os.path.join(_BASE_DIR, "static"))
    ruta = os.path.realpath(os.path.join(_BASE_DIR, ruta_url.lstrip("/")))
    if not ruta.startswith(base + os.sep) or not os.path.isfile(ruta):
        return None
    return ruta


def _voucher_como_imagen(ruta: str):
    """Voucher listo para el Word: (JPEG liviano, ancho_mm). Acepta JPG, PNG o PDF (1.ª hoja)."""
    try:
        from PIL import Image, ImageOps
        if ruta.lower().endswith(".pdf"):
            try:
                import pymupdf
            except ImportError:
                import fitz as pymupdf
            with pymupdf.open(ruta) as pdf:
                pix = pdf[0].get_pixmap(dpi=130)
                img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        else:
            img = ImageOps.exif_transpose(Image.open(ruta)).convert("RGB")
        img.thumbnail((1400, 1400))
        w, h = img.size
        ancho_mm = max(40.0, min(110.0, 125.0 * w / h))  # máx. ~12,5 cm de alto y 11 cm de ancho
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=85)
        buf.seek(0)
        return buf, ancho_mm
    except Exception:
        logger.exception("No se pudo preparar el voucher %s para el documento", ruta)
        return None


def _vouchers_para_documento(tpl, venta: m.Venta) -> list:
    """Voucher(s) del medio de pago que se insertan en el Contrato Preparatorio."""
    dc = venta.datos_credito or {}
    imagenes = []
    for url in [dc.get("voucher_url")]:
        ruta = _ruta_local_de_url(url)
        preparado = _voucher_como_imagen(ruta) if ruta else None
        if preparado:
            buf, ancho_mm = preparado
            imagenes.append(InlineImage(tpl, buf, width=Mm(ancho_mm)))
        elif url:
            logger.warning("Venta %s: no se encontró el voucher %s en el servidor", venta.id, url)
    return imagenes


def construir_firmas(rep: dict, clientes: list[m.Cliente]) -> list[dict]:
    """Filas de 2 firmantes: quien firma por la vendedora y cada comprador. Todo sale de la venta."""
    firmantes = [(
        (rep["nombre"] or "").upper(),
        f"LA VENDEDORA · DNI N° {rep['dni'] or ''}",
    )]
    for cli in clientes:
        if cli.tipo_persona == "juridica":
            nombre = cli.representante_legal or cli.razon_social or cli.nombres
            detalle = (
                f"REPRESENTANTE DE {(cli.razon_social or '').upper()} · "
                f"{cli.representante_tipo_documento or 'DNI'} N° {cli.representante_numero_documento or ''}"
            )
        else:
            nombre = _nombre_cliente(cli)
            detalle = f"{'COMPRADORA' if _es_mujer(cli) else 'COMPRADOR'} · DNI N° {_documento_cliente(cli)}"
        firmantes.append((nombre.upper(), detalle))

    filas = []
    for i in range(0, len(firmantes), 2):
        izq = firmantes[i]
        der = firmantes[i + 1] if i + 1 < len(firmantes) else ("", "")
        filas.append({
            "izq_linea": "_" * 30, "izq_nombre": izq[0], "izq_detalle": izq[1],
            "der_linea": "_" * 30 if der[0] else "", "der_nombre": der[0], "der_detalle": der[1],
        })
    return filas


# --------------------------------------------------------- generación -----

def generar_documento_venta(db: Session, venta: m.Venta, firmante: str = "gerente") -> bytes:
    """Rellena la plantilla según forma_pago y devuelve el PDF ya convertido.
    firmante: 'gerente' (gerente general) o 'apoderado' = quién comparece por la empresa."""
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
    rep = datos_firmante(empresa, firmante)

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
        "empresa_representante_bloque": construir_bloque_representante(
            "contrato" if modo == "preparatorio" else "minuta", firmante, rep, empresa
        ),
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

        "proyecto_nombre": (proyecto.nombre if proyecto else "").upper(),
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
        "texto_intereses": "",
        "firmas": construir_firmas(rep, clientes),
        "vouchers": [],
    })

    if venta.datos_credito:
        dc = venta.datos_credito
        fecha_deposito = date.fromisoformat(str(dc["fecha_deposito"]))
        plazo_meses = reglas.plazo_meses_de(dc)
        fecha_maxima = fecha_deposito + relativedelta(months=plazo_meses)
        tea = reglas.tea_aplicable(plazo_meses, dc.get("tea_financiamiento"))
        if plazo_meses % 12 == 0:
            anios = plazo_meses // 12
            plazo_texto = f"{numero_a_letras(anios)} AÑO" + ("S" if anios != 1 else "")
        else:
            plazo_texto = f"{numero_a_letras(plazo_meses)} MESES"
        ctx.update({
            "inicial_monto": f"{float(dc['inicial_monto']):,.2f}",
            "inicial_monto_texto": numero_a_letras(dc["inicial_monto"]),
            "fecha_deposito": _fecha_texto(fecha_deposito),
            "numero_operacion": dc.get("numero_operacion", ""),
            "plazo_texto": plazo_texto,
            "fecha_maxima_pago": _fecha_texto(fecha_maxima),
            "tasa_interes_compensatorio": f"{dc.get('tasa_interes', 25)}",
            "texto_intereses": "SIN INTERESES" if tea == 0 else f"CON INTERESES A UNA TASA EFECTIVA ANUAL DEL {tea}%",
        })

    tpl = DocxTemplate(ruta_plantilla)
    if venta.forma_pago == m.FormaPagoEnum.credito:
        ctx["vouchers"] = _vouchers_para_documento(tpl, venta)
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


# ------------------------------------------------------- contrato formal --

def generar_contrato_desde_venta(db: Session, venta: m.Venta, usuario: m.Usuario) -> "m.Contrato":
    """Crea el Contrato formal (módulo Ventas y Contratos) con su cronograma. El lote pasa a 'vendido'."""
    if venta.id_contrato:
        raise HTTPException(status_code=409, detail="Esta venta ya tiene un contrato registrado")

    numero_contrato = f"V-{venta.id:06d}"
    fecha_abono = date.today()
    frecuencia = "mensual"
    numero_cuotas = 0
    tea = Decimal("0")
    observaciones = None
    filas: list[dict] = []

    if venta.forma_pago == m.FormaPagoEnum.contado:
        inicial_abonado = sum(
            (Decimal(str(p["monto"])) for p in (venta.pagos_previos or [])), Decimal("0")
        )
        saldo = Decimal("0")
        estado_contrato = m.EstadoContratoEnum.cancelado
    else:
        dc = venta.datos_credito or {}
        inicial_abonado = Decimal(str(dc.get("inicial_monto", 0)))
        saldo = max(venta.precio_total - inicial_abonado, Decimal("0"))
        observaciones = (dc.get("observaciones") or None)
        if dc.get("fecha_deposito"):
            fecha_abono = date.fromisoformat(str(dc["fecha_deposito"]))
        plazo_meses = reglas.plazo_meses_de(dc)
        frecuencia = dc.get("frecuencia_cuota", "mensual")
        if frecuencia not in reglas.FRECUENCIAS:
            frecuencia = "mensual"
        if saldo > 0:
            tea = reglas.tea_aplicable(plazo_meses, dc.get("tea_financiamiento"))
            filas = reglas.construir_cronograma(
                saldo, frecuencia, plazo_meses, tea, fecha_abono, dc.get("cuotas_personalizadas")
            )
            numero_cuotas = sum(1 for f in filas if f.get("requiere_pago", True))

            estado_contrato = m.EstadoContratoEnum.vigente
        else:
            estado_contrato = m.EstadoContratoEnum.cancelado

    tem = None
    if tea > 0:
        tem = Decimal(str(((1 + float(tea) / 100) ** (1 / 12) - 1) * 100)).quantize(Decimal("0.001"))

    contrato = m.Contrato(
        numero_contrato=numero_contrato,
        id_lote=venta.id_lote,
        id_proyecto=venta.id_proyecto,
        id_empresa=venta.id_empresa,
        fecha_contrato=date.today(),
        precio_total=venta.precio_total,
        inicial_abonado=inicial_abonado,
        fecha_abono=fecha_abono,
        forma_pago=venta.forma_pago,
        frecuencia_cuota="custom" if frecuencia == "personalizado" else frecuencia,
        saldo_financiado=saldo,
        numero_cuotas=numero_cuotas,
        tiene_interes=tea > 0,
        tea=tea if tea > 0 else None,
        tem=tem,
        fecha_inicio_interes=fecha_abono if tea > 0 else None,
        tipo_contrato="Minuta" if venta.forma_pago == m.FormaPagoEnum.contado else "Contrato Preparatorio",
        observaciones=observaciones[:300] if observaciones else None,
        estado=estado_contrato,
        id_usuario_registro=usuario.id,
    )
    db.add(contrato)
    db.flush()

    for vc in venta.clientes_rel:
        db.add(m.ContratoCliente(id_contrato=contrato.id, id_cliente=vc.id_cliente, rol=vc.rol))

    for f in filas:
        db.add(m.CronogramaPago(
            id_contrato=contrato.id,
            numero_cuota=f["numero"],
            fecha_pago_programada=f["fecha"],
            capital=f["capital"],
            amortizacion=f["amortizacion"],
            interes_mensual=f["interes"],
            interes_acumulado=f["acumulado"],
            monto_cuota=f["monto"],
            requiere_pago=f.get("requiere_pago", True),
        ))

    # --- Pagos de la inicial: entran al circuito Caja -> Facturación ---
    if venta.forma_pago == m.FormaPagoEnum.contado:
        origen = [
            (Decimal(str(p["monto"])), p.get("fecha"), p.get("numero_operacion"), p.get("voucher_url"))
            for p in (venta.pagos_previos or [])
        ]
    else:
        dc_ini = venta.datos_credito or {}
        origen = [(
            Decimal(str(dc_ini.get("inicial_monto", 0))),
            dc_ini.get("fecha_deposito"),
            dc_ini.get("numero_operacion"),
            dc_ini.get("voucher_url"),
        )]

    for monto_p, fecha_p, nro_op, voucher in origen:
        if monto_p <= 0:
            continue
        db.add(m.Pago(
            id_contrato=contrato.id,
            id_cuota=None,
            monto=monto_p,
            fecha_pago=date.fromisoformat(str(fecha_p)) if fecha_p else date.today(),
            numero_operacion=(str(nro_op)[:50] if nro_op else None),
            comprobante_url=voucher,
            observacion=f"Inicial de la venta #{venta.id}",
            tipo="contado" if venta.forma_pago == m.FormaPagoEnum.contado else "inicial",
            estado="pendiente_caja",
            registrado_por=usuario.id,
        ))

    venta.id_contrato = contrato.id

    lote = db.query(m.Lote).filter(m.Lote.id == venta.id_lote).first()
    if lote and lote.estado != m.EstadoLoteEnum.vendido:
        anterior = lote.estado
        lote.estado = m.EstadoLoteEnum.vendido
        lote.actualizado_por = usuario.id
        db.add(m.LoteEstadoHistorial(
            id_lote=lote.id, estado_anterior=anterior, estado_nuevo=m.EstadoLoteEnum.vendido,
            id_usuario=usuario.id,
            observacion=f"Vendido mediante venta #{venta.id} (contrato {numero_contrato})",
        ))

    return contrato