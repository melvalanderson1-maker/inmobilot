export interface Rol {
  id: number;
  clave: string;
  nombre: string;
}

export interface Modulo {
  id: number;
  clave: string;
  nombre: string;
  ruta: string;
}

export interface UsuarioMe {
  id: number;
  nombre: string;
  correo: string;
  telefono?: string;
  rol: Rol;
  id_empresa?: number;
  modulos: Modulo[];
  proyectos: number[];
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  usuario: UsuarioMe;
}

export type EstadoLote = 'libre' | 'vendido' | 'bloqueado' | 'separado';

export interface LoteImagen {
  id: number;
  url: string;
  orden: number;
  es_portada: boolean;
}

export interface Lote {
  id: number;
  id_proyecto: number;
  id_manzana: number;
  codigo: string;
  ubicacion_lote?: string;
  perimetro?: number;
  area_m2: number;
  precio_m2_base?: number;
  precio_total_base?: number;
  precio_m2_contado?: number;
  precio_total_contado?: number;
  inicial_financiado?: number;
  monto_financiado?: number;
  precio_total_financiado?: number;
  estado: EstadoLote;
  partida_registral?: string;
  sunarp_url?: string;
  activo: boolean;
  imagenes: LoteImagen[];
}

export interface LotePublico {
  id: number;
  codigo: string;
  ubicacion_lote?: string;
  area_m2: number;
  precio_total_base?: number;
  precio_total_contado?: number;
  precio_total_financiado?: number;
  url: string;
  estado: EstadoLote;
  imagenes: LoteImagen[];
}

export interface Proyecto {
  id: number;
  id_empresa: number;
  nombre: string;
  slug: string;
  departamento?: string;
  provincia?: string;
  distrito?: string;
  descripcion?: string;
  logo_url?: string;
  moneda: string;
  activo: boolean;
}

export interface ProyectoCreate {
  nombre: string;
  slug: string;
  departamento?: string;
  provincia?: string;
  distrito?: string;
  descripcion?: string;
  logo_url?: string;
  moneda?: string;
}

export interface Etapa {
  id: number;
  id_proyecto: number;
  nombre: string;
  partida_registral: string;
  sunarp_url?: string;
  orden: number;
}

export interface EtapaCreate {
  id_proyecto: number;
  nombre: string;
  partida_registral: string;
  sunarp_url?: string;
  orden?: number;
}

export interface EtapaUpdate {
  nombre?: string;
  partida_registral?: string;
  sunarp_url?: string;
  orden?: number;
}

export interface Manzana {
  id: number;
  id_proyecto: number;
  id_etapa: number;
  nombre: string;
  etapa?: Etapa;
}

export interface ManzanaCreate {
  id_proyecto: number;
  id_etapa: number;
  nombre: string;
}

export type EstadoLead = 'nuevo' | 'contactado' | 'en_seguimiento' | 'convertido' | 'descartado';
export type OrigenLead = 'web' | 'whatsapp' | 'facebook' | 'instagram' | 'referido' | 'otro';

export interface Lead {
  id: number;
  id_proyecto: number;
  id_lote?: number;
  nombre?: string;
  telefono?: string;
  correo?: string;
  mensaje?: string;
  origen: OrigenLead;
  estado: EstadoLead;
  id_ejecutivo_asignado?: number;
  created_at: string;
}

export interface LeadSeguimiento {
  id: number;
  id_lead: number;
  id_usuario?: number;
  nota?: string;
  created_at: string;
}

export interface Notificacion {
  id: number;
  tipo: string;
  titulo: string;
  mensaje?: string;
  data?: Record<string, unknown>;
  leido: boolean;
  created_at: string;
}



export interface Rol {
  id: number;
  clave: string;
  nombre: string;
}

export interface Usuario {
  id: number;
  nombre: string;
  correo: string;
  telefono?: string;
  id_rol: number;
  rol: Rol;
  id_empresa?: number;
  activo: boolean;
  created_at: string;
  proyectos: number[];
}

export interface UsuarioCreate {
  nombre: string;
  correo: string;
  password: string;
  telefono?: string;
  id_rol: number;
  proyectos: number[];
}

export interface UsuarioUpdate {
  nombre?: string;
  correo?: string;
  password?: string;
  telefono?: string;
  id_rol?: number;
  activo?: boolean;
  proyectos?: number[];
}



export type FormaPago = 'contado' | 'credito';
export type EstadoContrato = 'vigente' | 'cancelado' | 'moroso' | 'anulado';
export type EstadoCuota = 'pendiente' | 'pagada' | 'vencida' | 'parcial';
export type RolClienteContrato = 'titular' | 'conyuge' | 'copropietario';

export interface ClienteCreate {
  tipo_documento: string;
  numero_documento: string;
  nombres: string;
  apellidos: string;
  correo?: string;
  telefono?: string;
  direccion?: string;
}

export interface ContratoClienteIn {
  id_cliente?: number;
  cliente_nuevo?: ClienteCreate;
  rol: RolClienteContrato;
}

export interface ContratoCreate {
  numero_contrato: string;
  id_lote: number;
  fecha_contrato: string;
  precio_total: number;
  inicial_abonado: number;
  fecha_abono?: string;
  tiene_interes: boolean;
  forma_pago: FormaPago;
  frecuencia_cuota: string;
  saldo_financiado: number;
  numero_cuotas: number;
  tea?: number;
  tcea?: number;
  tem?: number;
  fecha_inicio_interes?: string;
  tipo_contrato?: string;
  observaciones?: string;
  clientes: ContratoClienteIn[];
}

export interface ContratoLote {
  id: number;
  codigo: string;
  ubicacion_lote?: string;
}

export interface ContratoClienteInfo {
  id_cliente: number;
  nombres: string;
  apellidos: string;
  numero_documento: string;
  rol: RolClienteContrato;
}

export interface Contrato {
  id: number;
  numero_contrato: string;
  id_lote: number;
  id_proyecto: number;
  fecha_contrato: string;
  precio_total: number;
  inicial_abonado: number;
  forma_pago: FormaPago;
  frecuencia_cuota: string;
  saldo_financiado: number;
  numero_cuotas: number;
  tipo_contrato?: string;
  observaciones?: string;
  estado: EstadoContrato;
  lote?: ContratoLote;
  clientes: ContratoClienteInfo[];
}


export interface CronogramaCuota {
  id: number;
  numero_cuota: number;
  fecha_pago_programada: string;
  capital?: number;
  amortizacion?: number;
  interes_mensual?: number;
  interes_acumulado?: number;
  monto_cuota: number;
  requiere_pago: boolean;
  estado: EstadoCuota;
  monto_pagado: number;
  fecha_pago_real?: string;
}

export interface PagoCreate {
  id_cuota?: number;
  monto: number;
  fecha_pago: string;
  metodo_pago?: string;
  numero_operacion?: string;
  comprobante_url: string;
  observacion?: string;
}


export interface Pago {
  id: number;
  id_cuota?: number;
  id_contrato: number;
  monto: number;
  fecha_pago: string;
  metodo_pago?: string;
  numero_operacion?: string;
  comprobante_url?: string;
}