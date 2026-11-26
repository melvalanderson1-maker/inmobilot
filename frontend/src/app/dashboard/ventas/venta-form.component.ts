import { DecimalPipe } from '@angular/common';
import { Component, HostListener, OnDestroy, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';

import { SeparacionService } from '../../core/services/separacion.service';
import { ClienteService } from '../../core/services/cliente.service';
import { VentaService } from '../../core/services/venta.service';
import { ToastService } from '../../core/services/toast.service';
import { Separacion, FormaPago, Cliente, Lote, Proyecto, AutorizacionVenta, VentaClienteIn, VentaCreate, EvaluacionVenta } from '../../core/models';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { ClienteBuscadorComponent } from '../../shared/cliente-buscador/cliente-buscador.component';

import { BorradorService } from '../../core/services/borrador.service';
import { comprimirImagen } from '../../core/utils/comprimir-imagen';

type RolExtra = 'conyuge' | 'copropietario';
interface PagoPrevio {
  monto: number | null;
  fecha: string;
  numero_operacion: string;
  voucher_url: string;
}
interface CompradorExtra {
  cliente: Cliente;
  rol: RolExtra;
}


interface FilaSim {
  numero: number;
  fecha: string;
  capital: number; // capital vigente ANTES de amortizar
  amortizacion: number;
  interes: number;
  monto: number; // cuota
  ajustada: boolean;
  requiere_pago: boolean;
  pagoAnual: boolean; // última fila de cada año
}
interface Simulado {
  tea: number;
  financiar: number;
  cuota: number;
  filas: FilaSim[];
  anual: { fila: any; capitalAntes: number }[];
}

@Component({
  selector: 'app-venta-form',
  standalone: true,
  imports: [FormsModule, DecimalPipe, ClienteBuscadorComponent],
  templateUrl: './venta-form.component.html',
  styleUrl: './venta-form.component.css',
})
export class VentaFormComponent implements OnInit, OnDestroy {
  private readonly borrador = inject(BorradorService);
  private readonly separacionService = inject(SeparacionService);
  private readonly clienteService = inject(ClienteService);
  private readonly ventaService = inject(VentaService);
  private readonly toastService = inject(ToastService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);

  private readonly api = inject(ApiService);
  private readonly auth = inject(AuthService);

  readonly MAX_EXTRAS = 3; // titular + 3 = 4 compradores
  readonly plazosRapidos = [12, 24, 36, 48, 60];

  idSeparacion!: number;
  separacion = signal<Separacion | null>(null);
  cargando = signal(false);
  guardando = signal(false);
  subiendoVoucher = signal(false);
  error = signal<string | null>(null);

  formaPago: FormaPago = 'contado';
  precioTotal: number | null = null;
  /** true cuando el usuario cambió el precio a mano (ya no se reemplaza solo al cambiar la forma de pago) */
  precioEditado = false;
  fechaLimiteSaldo = '';

  pagosPrevios: PagoPrevio[] = [{ monto: null, fecha: '', numero_operacion: '', voucher_url: '' }];
  subiendoVoucherPago = signal<number | null>(null);

  datosCredito = {
    inicial_monto: null as number | null,
    fecha_deposito: '',
    numero_operacion: '',
    plazo_meses: 24,
    frecuencia_cuota: 'mensual',
    tasa_interes: 25,
    tea_financiamiento: null as number | null,
    observaciones: '',
    voucher_url: '',
  };

  frecuencias = [
    { valor: 'mensual', etiqueta: 'Mensual' },
    { valor: 'bimestral', etiqueta: 'Bimestral' },
    { valor: 'trimestral', etiqueta: 'Trimestral' },
    { valor: 'semestral', etiqueta: 'Semestral' },
    { valor: 'anual', etiqueta: 'Anual (con detalle mensual)' },
    { valor: 'unico', etiqueta: 'Pago único al vencimiento' },
    { valor: 'personalizado', etiqueta: 'Cronograma personalizado' },
  ];

  // ---- Cronograma personalizado ----
  cuotasPers: { fecha: string; monto: number | null }[] = [];
  genN = 4;
  genCada = 3;
  readonly opcionesCada = [1, 2, 3, 6, 12];

  // ---- Vista previa de reglas (la calcula el backend) ----
  evaluacion = signal<EvaluacionVenta | null>(null);
  errorEvaluacion = signal<string | null>(null);
  private timer: ReturnType<typeof setTimeout> | null = null;

  // ---- Compradores adicionales ----
  extras = signal<CompradorExtra[]>([]);
  agregando = signal(false);
  conyugeTitular = signal<{ nombres: string; apellidos: string; numero_documento: string } | null>(null);
  creandoConyuge = signal(false);

  idsExcluidos = computed(() => [this.separacion()?.id_cliente ?? 0, ...this.extras().map((e) => e.cliente.id)]);
  puedeAgregarMas = computed(() => this.extras().length < this.MAX_EXTRAS);
  conyugeDisponible = computed(() => {
    const cy = this.conyugeTitular();
    if (!cy) return false;
    return !this.extras().some((e) => e.cliente.numero_documento === cy.numero_documento);
  });

  // ---- Precios de referencia (vienen del lote y de la separación) ----
  precios = computed(() => {
    const s = this.separacion();
    const l = s?.lote;
    return {
      regular: this.positivo(l?.precio_total_base),
      contado: this.positivo(l?.precio_total_contado),
      financiado: this.positivo(l?.precio_total_financiado),
      // precio final acordado en la separación; si no se definió, el contado de lista
      pactado: this.positivo(s?.precio_descontado) ?? this.positivo(l?.precio_total_contado),
    };
  });


  // ---------------- VENTA DIRECTA (sin separación) ----------------
  directo = false;
  proyectos = signal<Proyecto[]>([]);
  idProyecto: number | null = null;
  lotesDirecto = signal<Lote[]>([]);
  idLoteDirecto: number | null = null;
  titularDirecto = signal<Cliente | null>(null);
  autorizaciones = signal<AutorizacionVenta[]>([]);
  private readonly CLAVE_SEL = 'venta-directa-sel';

  /** Borrador de venta directa encontrado al entrar: el usuario decide si lo retoma o lo descarta */
  borradorPendiente = signal<{
    idLote: number | null;
    idTitular: number | null;
    lote: string | null;
    titular: string | null;
  } | null>(null);

  /** Modal "tienes cambios sin guardar" */
  confirmarSalida = signal(false);

  /** Respuesta pendiente del guard de ruta (solo existe cuando el modal lo abrió el guard) */
  private resolverGuard: ((puedeSalir: boolean) => void) | null = null;

  /** true mientras se descarta: evita que el autoguardado reviva el borrador */
  private descartando = false;
  get puedeResolver(): boolean {
    return ['admin', 'gerencia'].includes(this.auth.usuario()?.rol?.clave ?? '');
  }

  /** Mismo flag que separacion-detalle y el backend (PERMITIR_EDITAR_TODO). Poner en false al terminar la carga histórica. */
  readonly permitirEditarTodo = true;

  /** Con carga histórica activa, admin/gerencia crean la venta sin pedir autorización */
  get omitirAutorizacion(): boolean {
    return this.permitirEditarTodo && this.puedeResolver;
  }
  private iniciarDirecto(): void {
    const idNuevo = Number(this.route.snapshot.queryParamMap.get('id_cliente')) || null;
    this.api.get<Proyecto[]>('/proyectos').subscribe((ps) => {
      this.proyectos.set(ps);
      const sel = this.borrador.leer<{ idProyecto: number | null; idLote: number | null; idTitular: number | null }>(this.CLAVE_SEL);
      this.idProyecto = sel?.idProyecto ?? ps[0]?.id ?? null;
      this.idLoteDirecto = sel?.idLote ?? null;
      if (!this.idProyecto) return;

      // Hay un borrador y NO venimos de crear un cliente: preguntar antes de entrar
      if ((sel?.idLote || sel?.idTitular) && !idNuevo) {
        this.borradorPendiente.set({ idLote: sel.idLote, idTitular: sel.idTitular, lote: null, titular: null });
        this.cargarLotesDirecto(() => {
          const l = this.lotesDirecto().find((x) => x.id === sel.idLote);
          this.borradorPendiente.update((b) => (b ? { ...b, lote: l?.codigo ?? null } : b));
        });
        if (sel.idTitular) {
          this.clienteService.obtener(sel.idTitular).subscribe((c) =>
            this.borradorPendiente.update((b) => (b ? { ...b, titular: `${c.nombres} ${c.apellidos}` } : b))
          );
        }
        return;
      }

      this.retomar(sel, idNuevo);
    });
  }

  /** Entra al formulario con la selección guardada (o con el cliente recién creado) */
  private retomar(
    sel: { idProyecto: number | null; idLote: number | null; idTitular: number | null } | null,
    idNuevo: number | null
  ): void {
    this.cargarLotesDirecto(() => {
      const idTit = sel?.idTitular ?? idNuevo;
      if (!idTit) return;
      this.clienteService.obtener(idTit).subscribe((c) => {
        this.titularDirecto.set(c);
        this.armarSeparacionVirtual();
        if (sel?.idTitular && idNuevo && idNuevo !== sel.idTitular) {
          this.clienteService.obtener(idNuevo).subscribe((x) => this.agregarComprador(x));
        }
      });
    });
  }

  /** Botón "Continuar donde quedé" */
  retomarBorrador(): void {
    this.borradorPendiente.set(null);
    const sel = this.borrador.leer<{ idProyecto: number | null; idLote: number | null; idTitular: number | null }>(this.CLAVE_SEL);
    this.retomar(sel, null);
  }

  /** Botón "Empezar una nueva": borra el borrador y deja la pantalla limpia */
  descartarBorradorInicial(): void {
    const bp = this.borradorPendiente();
    if (bp?.idLote) this.borrador.borrar(`venta-directa-${bp.idLote}`);
    this.borrador.borrar(this.CLAVE_SEL);
    this.idLoteDirecto = null;
    this.titularDirecto.set(null);
    this.borradorPendiente.set(null);
  }

  cargarLotesDirecto(despues?: () => void): void {
    if (!this.idProyecto) return;
    this.api.get<Lote[]>('/lotes', { id_proyecto: this.idProyecto }).subscribe((ls) => {
      this.lotesDirecto.set(ls);
      despues?.();
    });
  }

  onProyectoDirecto(): void {
    this.idLoteDirecto = null;
    this.lotesDirecto.set([]);
    this.cargarLotesDirecto();
    this.guardarSeleccion();
  }

  etiquetaLoteDirecto(l: Lote): string {
    return `${l.codigo} — ${l.ubicacion_lote || 'sin ubicación'} — ${l.estado}`;
  }

  elegirTitularDirecto(c: Cliente): void {
    this.titularDirecto.set(c);
    this.guardarSeleccion();
  }

  guardarSeleccion(): void {
    if (this.descartando) return;
    this.borrador.guardarYa(this.CLAVE_SEL, {
      idProyecto: this.idProyecto,
      idLote: this.idLoteDirecto,
      idTitular: this.titularDirecto()?.id ?? null,
    });
  }

  /** Arma una "separación" en memoria (sin guardarla) para reutilizar todo el formulario */
  armarSeparacionVirtual(): void {
    const lote = this.lotesDirecto().find((l) => l.id === this.idLoteDirecto);
    const cli = this.titularDirecto();
    if (!lote || !cli) {
      this.error.set('Elige el lote y el cliente titular');
      return;
    }
    this.error.set(null);
    const hoy = new Date().toISOString().slice(0, 10);
    this.separacion.set({
      id: 0,
      id_proyecto: lote.id_proyecto,
      id_lote: lote.id,
      id_cliente: cli.id,
      id_ejecutivo: 0,
      fecha_inicio: hoy,
      fecha_vencimiento: hoy,
      importe: 0,
      estado: 'convertida',
      dni_frente_url: '',
      voucher_url: '',
      created_at: hoy,
      comprobantes: [],
      devoluciones: [],
      cliente: {
        id: cli.id,
        numero_documento: cli.numero_documento,
        nombres: cli.nombres,
        apellidos: cli.apellidos,
        telefono: cli.telefono,
      },
      lote: {
        id: lote.id,
        codigo: lote.codigo,
        ubicacion_lote: lote.ubicacion_lote,
        perimetro: lote.perimetro,
        frontis: lote.frontis,
        sunarp_url: lote.sunarp_url ?? undefined,
        area_m2: lote.area_m2,
        partida_registral: lote.partida_registral,
        precio_total_base: lote.precio_total_base,
        precio_total_contado: lote.precio_total_contado,
        precio_total_financiado: lote.precio_total_financiado,
        estado: lote.estado,
      },
    } as Separacion);
    this.guardarSeleccion();
    this.precioTotal = this.precioSugerido();
    this.precioEditado = false;
    this.base = this.instantanea();
    this.restaurarBorrador();
    this.conyugeTitular.set(cli.conyuge ?? null);
    this.reevaluar();
    this.cargarAutorizaciones();
  }

  reiniciarDirecto(): void {
    this.salidaLibre = true;
    this.separacion.set(null);
    this.extras.set([]);
    this.evaluacion.set(null);
    this.autorizaciones.set([]);
    this.titularDirecto.set(null);
    this.guardarSeleccion();
    this.salidaLibre = false;
  }

  cargarAutorizaciones(): void {
    if (!this.directo || !this.idLoteDirecto) return;
    this.ventaService.listarAutorizacionesLote(this.idLoteDirecto).subscribe((a) => this.autorizaciones.set(a));
  }

  resolverAut(a: AutorizacionVenta, aprobar: boolean): void {
    this.ventaService.resolverAutorizacion(a.id, aprobar).subscribe({
      next: () => this.cargarAutorizaciones(),
      error: (err) => this.toastService.error(err?.error?.detail ?? 'No se pudo resolver'),
    });
  }

  crearAutorizada(a: AutorizacionVenta): void {
    this.guardando.set(true);
    this.ventaService.crearDesdeAutorizacion(a.id).subscribe({
      next: (venta) => {
        this.guardando.set(false);
        this.finalizarBorradores();
        this.toastService.exito('Venta creada con las condiciones autorizadas');
        this.router.navigate(['/dashboard/contratos/venta', venta.id]);
      },
      error: (err) => this.fallo(err, 'No se pudo crear la venta'),
    });
  }

  private evaluarServidor(p: VentaCreate) {
    return this.directo ? this.ventaService.evaluarDirecta(p) : this.ventaService.evaluar(this.idSeparacion, p);
  }

  private finalizarBorradores(): void {
    this.borrador.borrar(this.claveBorrador());
    if (this.directo) this.borrador.borrar(this.CLAVE_SEL);
    this.salidaLibre = true;
  }



  ngOnInit(): void {
    const p = this.route.snapshot.paramMap.get('id');
    this.directo = !p;
    this.idSeparacion = Number(p) || 0;
    if (this.directo) this.iniciarDirecto();
    else this.cargar();
  }

  ngOnDestroy(): void {
    if (this.timer) clearTimeout(this.timer);
  }

  private positivo(v: unknown): number | null {
    if (v === null || v === undefined || v === '') return null;
    const n = Number(v);
    return Number.isFinite(n) && n > 0 ? n : null;
  }


    private base = '';
  private salidaLibre = false;

  private instantanea(): string {
    return JSON.stringify({
      f: this.formaPago,
      p: this.precioTotal,
      pp: this.pagosPrevios,
      fl: this.fechaLimiteSaldo,
      dc: this.datosCredito,
      cp: this.cuotasPers,
      e: this.extras().map((x) => x.cliente.id),
      l: this.idLoteDirecto,
    });
  }

  tieneCambiosSinGuardar(): boolean {
    return !this.salidaLibre && this.base !== '' && this.instantanea() !== this.base;
  }

  @HostListener('window:beforeunload', ['$event'])
  avisarAlCerrar(e: BeforeUnloadEvent): void {
    if (this.tieneCambiosSinGuardar()) {
      e.preventDefault();
      e.returnValue = '';
    }
  }
  // ---- Borrador: se guarda solo y se recupera al recargar o volver ----

  private claveBorrador(): string {
    return this.directo ? `venta-directa-${this.idLoteDirecto}` : `venta-${this.idSeparacion}`;
  }

  guardarBorrador(ahora = false): void {
    if (this.descartando || this.cargando() || !this.separacion()) return;
    const datos = {
      formaPago: this.formaPago,
      precioTotal: this.precioTotal,
      precioEditado: this.precioEditado,
      pagosPrevios: this.pagosPrevios,
      fechaLimiteSaldo: this.fechaLimiteSaldo,
      datosCredito: this.datosCredito,
      cuotasPers: this.cuotasPers,
      extras: this.extras(),
    };
    if (ahora) this.borrador.guardarYa(this.claveBorrador(), datos);
    else this.borrador.guardar(this.claveBorrador(), datos);
  }

  private restaurarBorrador(): void {
    const b = this.borrador.leer<any>(this.claveBorrador());
    if (!b) return;
    this.formaPago = b.formaPago ?? this.formaPago;
    this.precioTotal = b.precioTotal ?? this.precioTotal;
    this.precioEditado = b.precioEditado ?? this.precioEditado;
    if (b.pagosPrevios?.length) this.pagosPrevios = b.pagosPrevios;
    this.fechaLimiteSaldo = b.fechaLimiteSaldo ?? this.fechaLimiteSaldo;
    if (b.datosCredito) this.datosCredito = { ...this.datosCredito, ...b.datosCredito };
    if (b.cuotasPers?.length) this.cuotasPers = b.cuotasPers;
    if (b.extras?.length) this.extras.set(b.extras);
    this.toastService.exito('Se recuperó un borrador sin guardar');
  }

  cargar(): void {
    this.cargando.set(true);
    this.separacionService.obtener(this.idSeparacion).subscribe({
      next: (res) => {
        this.separacion.set(res);
        if (res.tipo_pago) this.formaPago = res.tipo_pago;
        this.precioTotal = this.precioSugerido();
        this.precioEditado = false;
        this.base = this.instantanea();
        this.restaurarBorrador();
        this.cargando.set(false);
        this.reevaluar();

        this.clienteService.obtener(res.id_cliente).subscribe((titular) => {
          this.conyugeTitular.set(titular.conyuge ?? null);
        });

        const idNuevo = Number(this.route.snapshot.queryParamMap.get('id_cliente'));
        if (idNuevo && idNuevo !== res.id_cliente) {
          this.clienteService.obtener(idNuevo).subscribe((c) => this.agregarComprador(c));
        }
      },
      error: () => this.cargando.set(false),
    });
  }

  // ---- Precio ----

  /** Precio que el sistema propone: el precio final pactado en la separación (descontado) */
  precioSugerido(): number | null {
    const p = this.precios();
    return p.pactado ?? p.financiado ?? p.regular;
  }

  get origenSugerido(): string {
    return this.precios().pactado !== null
      ? 'el precio final acordado en la separación'
      : 'el precio de lista del lote';
  }

  seleccionarForma(forma: FormaPago): void {
    if (this.formaPago === forma) return;
    this.formaPago = forma;
    this.reevaluar();
  }

  onPrecioManual(): void {
    this.precioEditado = true;
    this.reevaluar();
  }

  usarPrecio(valor: number | null): void {
    if (valor === null) return;
    this.precioTotal = valor;
    this.precioEditado = valor !== this.precioSugerido();
    this.reevaluar();
  }

  restablecerPrecio(): void {
    this.precioTotal = this.precioSugerido();
    this.precioEditado = false;
    this.reevaluar();
  }

  /** Descuento contra el precio regular del lote (negativo = por encima del regular) */
  get descuento(): number | null {
    const regular = this.precios().regular;
    if (!regular || !this.precioTotal) return null;
    return regular - this.precioTotal;
  }

  get descuentoPct(): number | null {
    const regular = this.precios().regular;
    const d = this.descuento;
    if (!regular || d === null) return null;
    return (d / regular) * 100;
  }

  get importeSeparado(): number {
    return Number(this.separacion()?.importe ?? 0);
  }

  // ---- Pagos previos (contado) ----

  get totalPagosPrevios(): number {
    return this.pagosPrevios.reduce((acc, p) => acc + (Number(p.monto) || 0), 0);
  }

  get saldoContado(): number | null {
    if (!this.precioTotal) return null;
    return Math.max(this.precioTotal - this.totalPagosPrevios, 0);
  }

  get pagosExcedenPrecio(): boolean {
    return !!this.precioTotal && this.totalPagosPrevios > this.precioTotal;
  }

  get pagoSeparacionAgregado(): boolean {
    const sep = this.separacion();
    if (!sep) return false;
    return this.pagosPrevios.some((p) => Number(p.monto) === this.importeSeparado && p.fecha === sep.fecha_inicio);
  }

  agregarPagoSeparacion(): void {
    const sep = this.separacion();
    if (!sep || this.pagoSeparacionAgregado) return;
    const fila: PagoPrevio = {
      monto: this.importeSeparado,
      fecha: sep.fecha_inicio,
      numero_operacion: (sep as any).voucher_numero ?? '',
      voucher_url: sep.voucher_url || '',
    };
    const vacia = this.pagosPrevios.findIndex((p) => !p.monto && !p.fecha);
    if (vacia >= 0) this.pagosPrevios[vacia] = fila;
    else this.pagosPrevios.push(fila);
  }

  agregarFilaPago(): void {
    this.pagosPrevios.push({ monto: null, fecha: '', numero_operacion: '', voucher_url: '' });
  }

  quitarFilaPago(index: number): void {
    this.pagosPrevios.splice(index, 1);
    if (this.pagosPrevios.length === 0) this.pagosPrevios.push({ monto: null, fecha: '', numero_operacion: '', voucher_url: '' });
  }


    async onVoucherPago(event: Event, index: number): Promise<void> {
    const input = event.target as HTMLInputElement;
    const archivo = input.files?.[0];
    input.value = '';
    if (!archivo) return;
    if (!['image/jpeg', 'image/png', 'application/pdf'].includes(archivo.type)) {
      this.toastService.error('Formato no permitido (usa JPG, PNG o PDF)');
      return;
    }
    if (archivo.size > 8 * 1024 * 1024) {
      this.toastService.error('El archivo debe pesar menos de 8MB');
      return;
    }
    this.subiendoVoucherPago.set(index);
    const formData = new FormData();
    formData.append('archivo', await comprimirImagen(archivo));
    this.ventaService.subirArchivo(formData).subscribe({
      next: (res) => {
        this.pagosPrevios[index].voucher_url = res.url;
        this.subiendoVoucherPago.set(null);
        this.guardarBorrador();
      },
      error: (err) => {
        this.subiendoVoucherPago.set(null);
        this.toastService.error(err?.error?.detail ?? 'No se pudo subir el voucher');
      },
    });
  }

  quitarVoucherPago(index: number): void {
    this.pagosPrevios[index].voucher_url = '';
  }

  // ---- Reglas ----

  get plazoTexto(): string {
    const m = Number(this.datosCredito.plazo_meses) || 0;
    if (m <= 0) return '';
    if (m % 12 === 0) return `${m / 12} año${m / 12 === 1 ? '' : 's'}`;
    return m > 12 ? `${Math.floor(m / 12)} año(s) y ${m % 12} mes(es)` : `${m} mes(es)`;
  }

  setPlazo(meses: number): void {
    this.datosCredito.plazo_meses = meses;
    this.reevaluar();
  }

  // ---- Valores automáticos según el plazo (más de 24 meses = método del Excel Gruselva) ----
  readonly TEA_LARGO = 20.98;   // TEA cuando el plazo supera 24 meses
  readonly MORA_CORTO = 25;     // mora (% anual) hasta 24 meses
  readonly MORA_LARGO = 40;     // mora (% anual) con más de 24 meses (pie del Excel)
  private autoTea: number | null = null;
  private autoMora = 25;
  private frecuenciaForzada = false;

  /** Pone TEA, mora y frecuencia según el plazo, sin pisar lo que el usuario escribió a mano */
  private aplicarDefectos(): void {
    if (this.esPersonalizado) return;
    const dc = this.datosCredito;
    const largo = Number(dc.plazo_meses) > 24;
    const nuevaTea = largo ? this.TEA_LARGO : null;
    const nuevaMora = largo ? this.MORA_LARGO : this.MORA_CORTO;

    if (dc.tea_financiamiento === this.autoTea) dc.tea_financiamiento = nuevaTea;
    if (Number(dc.tasa_interes) === this.autoMora) dc.tasa_interes = nuevaMora;
    this.autoTea = nuevaTea;
    this.autoMora = nuevaMora;

    if (largo && dc.frecuencia_cuota !== 'anual') {
      dc.frecuencia_cuota = 'anual';
      this.frecuenciaForzada = true;
    } else if (!largo && this.frecuenciaForzada) {
      dc.frecuencia_cuota = 'mensual';
      this.frecuenciaForzada = false;
    }
  }

  reevaluar(): void {
    this.aplicarDefectos();
    this.simulado.set(null); // el cronograma lo calcula SOLO el backend (una única fuente de verdad)
    if (this.timer) clearTimeout(this.timer);
    this.timer = setTimeout(() => this.evaluarAhora(), 350);
  }

  private armarPayload(paraEvaluar: boolean): VentaCreate {
    const sep = this.separacion()!;
    const clientes: VentaClienteIn[] = [
      { id_cliente: sep.id_cliente, rol: 'titular' },
      ...this.extras().map((e) => ({ id_cliente: e.cliente.id, rol: e.rol })),
    ];
    const dc = this.datosCredito;
    const hoy = new Date().toISOString().slice(0, 10);
    const pagosValidos = this.pagosPrevios.filter((p) => p.monto && p.fecha);

    return {
      id_lote: this.directo ? sep.id_lote : undefined,
      forma_pago: this.formaPago,
      precio_total: this.precioTotal ?? 0,
      clientes,
      pagos_previos: this.formaPago === 'contado' ? (pagosValidos as any) : undefined,
      fecha_limite_saldo: 
        this.formaPago === 'contado' && (this.saldoContado ?? 0) > 0 ? this.fechaLimiteSaldo || undefined : undefined,
      datos_credito:
        this.formaPago === 'credito' && dc.inicial_monto
          ? {
              inicial_monto: dc.inicial_monto,
              fecha_deposito: dc.fecha_deposito || (paraEvaluar ? hoy : ''),
              numero_operacion: dc.numero_operacion || (paraEvaluar ? '-' : ''),
              plazo_meses: Number(dc.plazo_meses) || 24,
              frecuencia_cuota: this.frecuenciaEfectiva,
              tasa_interes: dc.tasa_interes,
              tea_financiamiento:
                (this.esPersonalizado || Number(dc.plazo_meses) > 24) && dc.tea_financiamiento != null
                  ? dc.tea_financiamiento
                  : undefined,
              observaciones: dc.observaciones || undefined,
              voucher_url: dc.voucher_url || undefined,
              cuotas_personalizadas: this.esPersonalizado ? this.cuotasValidas() : undefined,
            }
          : undefined,
    };
  }

  private evaluarAhora(): void {
    if (!this.separacion() || !this.precioTotal || this.precioTotal <= 0) {
      this.evaluacion.set(null);
      return;
    }
    if (this.formaPago === 'credito' && !this.datosCredito.inicial_monto) {
      this.evaluacion.set(null);
      return;
    }
    if (this.formaPago === 'credito' && this.esPersonalizado && this.cuotasValidas().length === 0) {
      this.evaluacion.set(null);
      return;
    }
    this.evaluarServidor(this.armarPayload(true)).subscribe({
      next: (r) => {
        this.evaluacion.set(r);
        this.errorEvaluacion.set(null);
      },
      error: (err) => {
        this.evaluacion.set(null);
        const detalle = err?.error?.detail;
        const mensaje =
          typeof detalle === 'string'
            ? detalle
            : Array.isArray(detalle)
              ? detalle.map((d: any) => d?.msg ?? '').filter(Boolean).join('. ')
              : 'No se pudo calcular el cronograma. Revisa la respuesta del request evaluar en la pestaña Network.';
        this.errorEvaluacion.set(mensaje);
      },
    });
  }

  get requiereAutorizacion(): boolean {
    return !!this.evaluacion()?.requiere_autorizacion && !this.omitirAutorizacion;
  }

  // ---- Cronograma simulado (método de la hoja Excel: cuota mensual, interés por días reales) ----
  simulado = signal<Simulado | null>(null);

  private r2(n: number): number {
    return Math.round(n * 100) / 100;
  }



  /** Filas normalizadas: local si hay simulación, si no las del backend */
  get filasSimuladas(): FilaSim[] {
    const s = this.simulado();
    if (s) return s.filas;
    const ev: any = this.evaluacion();
    if (!ev) return [];
    const raw: any[] = ev.cronograma_mensual?.length ? ev.cronograma_mensual : (ev.cronograma ?? []);
    return raw.map((f, i) => {
      const paga = f.requiere_pago !== false;
      return {
        numero: f.numero,
        fecha: f.fecha,
        capital: !paga ? Number(f.capital) : i > 0 ? Number(raw[i - 1].capital) : Number(f.capital) + Number(f.amortizacion),
        amortizacion: Number(f.amortizacion),
        interes: Number(paga ? (f.acumulado ?? f.interes) : f.interes),
        monto: Number(f.monto),
        ajustada: !!f.ajustada,
        requiere_pago: paga,
        pagoAnual: paga,
      };
    });
  }

  /** TOTALES como en la hoja */
  get totalesSimulados(): { amortizacion: number; interes: number; cuota: number } {
    const s = this.simulado();
    if (s) {
      return {
        amortizacion: this.r2(s.filas.reduce((a, f) => a + f.amortizacion, 0)),
        interes: this.r2(s.filas.reduce((a, f) => a + f.interes, 0)),
        cuota: this.r2(s.filas.reduce((a, f) => a + f.monto, 0)),
      };
    }
    const ev: any = this.evaluacion();
    const cuota = this.filasSimuladas.filter((f) => f.requiere_pago).reduce((acc, f) => acc + f.monto, 0);
    const financiado = Number(ev?.monto_financiar ?? 0);
    const interes = ev?.interes_total != null ? this.r2(Number(ev.interes_total)) : this.r2(cuota - financiado);
    return { amortizacion: financiado, interes, cuota };
  }

  get financiarMostrado(): number {
    const s = this.simulado();
    return s ? s.financiar : Number((this.evaluacion() as any)?.monto_financiar ?? 0);
  }
  get cuotaMostrada(): number {
    const s = this.simulado();
    return s ? s.cuota : Number((this.evaluacion() as any)?.cuota_estimada ?? 0);
  }
  get pagosMostrados(): number {
    const s = this.simulado();
    return s ? s.filas.length : Number((this.evaluacion() as any)?.numero_cuotas ?? 0);
  }
  fmtFecha(f: string): string {
    const [y, m, d] = String(f).slice(0, 10).split('-');
    return `${d}/${m}/${y}`;
  }

  // ---- Libro de pagos: 30 filas en la página izquierda y 31 en la derecha ----
  readonly FILAS_IZQ = 30;
  readonly FILAS_DER = 31;
  spread = signal(0);

  get filasPorLibro(): number {
    return this.FILAS_IZQ + this.FILAS_DER;
  }

  get totalSpreads(): number {
    return Math.max(Math.ceil(this.filasSimuladas.length / this.filasPorLibro), 1);
  }

  get spreadActual(): number {
    return Math.min(this.spread(), this.totalSpreads - 1);
  }

  private tramo(desde: number, hasta: number): { fila: any; idx: number; capital: number }[] {
    return this.filasSimuladas
      .slice(desde, hasta)
      .map((fila, k) => ({ fila, idx: desde + k, capital: fila.capital }));
  }

  get paginas(): { fila: any; idx: number; capital: number }[][] {
    const o = this.spreadActual * this.filasPorLibro;
    return [this.tramo(o, o + this.FILAS_IZQ), this.tramo(o + this.FILAS_IZQ, o + this.filasPorLibro)];
  }

  rango(p: { fila: any }[]): string {
    return p.length ? `${p[0].fila.numero} a ${p[p.length - 1].fila.numero}` : '';
  }

  irSpread(n: number): void {
    this.spread.set(Math.min(Math.max(n, 0), this.totalSpreads - 1));
  }

  get hayCronograma(): boolean {
    return this.filasSimuladas.length > 0;
  }

  /** Los pagos del cronograma anual (hoja "cronograma anual" del Excel). Vacío si la frecuencia no es anual */
  get filasAnuales(): { fila: any; capitalAntes: number }[] {
    const s = this.simulado();
    if (s) return s.anual;
    const ev: any = this.evaluacion();
    if (!ev?.cronograma_mensual?.length) return [];
    const pagos: any[] = ev.cronograma ?? [];
    return pagos.map((fila, i) => ({
      fila,
      capitalAntes: i > 0 ? Number(pagos[i - 1].capital) : Number(fila.capital) + Number(fila.amortizacion),
    }));
  }

  /** Se resaltan las fechas de pago anual (cada 12 filas) */
  get resaltarPagos(): boolean {
    return !!this.simulado() || this.filasSimuladas.some((f) => f.requiere_pago === false);
  }

  get teaAplicada(): number {
    const s = this.simulado();
    return s ? s.tea : Number((this.evaluacion() as any)?.tea_aplicable ?? 0);
  }

  /** TEM = (1+TEA)^(1/12) - 1, igual que el Excel */
  get temAplicada(): number {
    return (Math.pow(1 + this.teaAplicada / 100, 1 / 12) - 1) * 100;
  }

  get plazoInvalidoAnual(): boolean {
    const p = Number(this.datosCredito.plazo_meses) || 0;
    return this.datosCredito.frecuencia_cuota === 'anual' && p > 0 && p % 12 !== 0;
  }

  get plazoSugeridoAnual(): number {
    return Math.max(12, Math.round((Number(this.datosCredito.plazo_meses) || 12) / 12) * 12);
  }

  ajustarPlazoAnual(): void {
    this.setPlazo(this.plazoSugeridoAnual);
  }

  /** Motivo por el que todavía no hay cronograma en pantalla */
  get razonSinCronograma(): string {
    const err = this.errorEvaluacion();
    if (err) return err;
    if (!this.precioTotal || this.precioTotal <= 0) return 'Indica el precio total de la venta.';
    if (!this.datosCredito.inicial_monto) return 'Ingresa el monto de la inicial para calcular el cronograma.';
    if (this.esPersonalizado && this.cuotasValidas().length === 0) return 'Agrega al menos una cuota con fecha.';
    return 'Calculando el cronograma...';
  }

  // ---- Cronograma personalizado ----

  get esPersonalizado(): boolean {
    return this.datosCredito.frecuencia_cuota === 'personalizado';
  }

  /** Más de 24 meses (y no personalizado) => siempre método anual con detalle mensual */
  get frecuenciaEfectiva(): string {
    if (this.esPersonalizado) return 'personalizado';
    return Number(this.datosCredito.plazo_meses) > 24 ? 'anual' : this.datosCredito.frecuencia_cuota;
  }

  get totalSimulado(): number {
    return (this.evaluacion()?.cronograma ?? []).reduce((acc, c) => acc + Number(c.monto), 0);
  }

  onFrecuenciaCambiada(): void {
    if (this.esPersonalizado && this.cuotasPers.length === 0) this.generarCuotas();
    this.reevaluar();
  }

  private aISO(d: Date): string {
    const p = (n: number) => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
  }

  /** Crea N filas con fecha cada X meses (sin monto: el sistema las calcula). */
  generarCuotas(): void {
    const n = Math.min(Math.max(Number(this.genN) || 1, 1), 60);
    const cada = Number(this.genCada) || 1;
    const base = this.datosCredito.fecha_deposito ? new Date(this.datosCredito.fecha_deposito + 'T00:00:00') : new Date();
    const filas: { fecha: string; monto: number | null }[] = [];
    for (let i = 1; i <= n; i++) {
      const y = base.getFullYear();
      const mes = base.getMonth() + i * cada;
      const ultimoDia = new Date(y, mes + 1, 0).getDate();
      filas.push({ fecha: this.aISO(new Date(y, mes, Math.min(base.getDate(), ultimoDia))), monto: null });
    }
    this.cuotasPers = filas;
    this.reevaluar();
  }

  agregarCuota(): void {
    this.cuotasPers.push({ fecha: '', monto: null });
  }

  quitarCuota(i: number): void {
    this.cuotasPers.splice(i, 1);
    this.reevaluar();
  }

  /** Filas con fecha, ordenadas, listas para enviar al servidor */
  cuotasValidas(): { fecha: string; monto: number | null }[] {
    return this.cuotasPers
      .filter((c) => !!c.fecha)
      .map((c) => ({ fecha: c.fecha, monto: c.monto && Number(c.monto) > 0 ? Number(c.monto) : null }))
      .sort((a, b) => a.fecha.localeCompare(b.fecha));
  }

  // ---- Estado de los pasos (para el indicador de progreso) ----

  get pasoPrecioOk(): boolean {
    return !!this.precioTotal && this.precioTotal > 0;
  }

  get pasoPagoOk(): boolean {
    if (this.formaPago === 'contado') {
      const filas = this.pagosPrevios.filter((p) => p.monto && p.fecha);
      const saldoOk = !(this.saldoContado && this.saldoContado > 0) || !!this.fechaLimiteSaldo;
      return filas.length > 0 && filas.every((p) => !!p.voucher_url) && !this.pagosExcedenPrecio && saldoOk;
    }
    const dc = this.datosCredito;
    const plazoOk = this.esPersonalizado ? this.cuotasValidas().length > 0 : !!dc.plazo_meses && dc.plazo_meses >= 1;
    return !!dc.inicial_monto && !!dc.fecha_deposito && !!dc.numero_operacion.trim() && !!dc.voucher_url && plazoOk;
  }
  irA(id: string): void {
    document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  // ---- Compradores adicionales ----

  agregarComprador(c: Cliente, rol: RolExtra = 'copropietario'): void {
    if (c.id === this.separacion()?.id_cliente) {
      this.toastService.error('Ese cliente ya es el comprador titular');
      return;
    }
    if (this.extras().some((e) => e.cliente.id === c.id)) {
      this.toastService.error('Ese cliente ya está agregado');
      return;
    }
    if (this.extras().length >= this.MAX_EXTRAS) {
      this.toastService.error('Una venta admite como máximo 4 compradores');
      return;
    }
    this.extras.update((lista) => [...lista, { cliente: c, rol }]);
    this.agregando.set(false);
  }

  quitarComprador(idCliente: number): void {
    this.extras.update((lista) => lista.filter((e) => e.cliente.id !== idCliente));
  }

  cambiarRol(idCliente: number, rol: RolExtra): void {
    this.extras.update((lista) => lista.map((e) => (e.cliente.id === idCliente ? { ...e, rol } : e)));
  }

  irACrearCliente(texto: string): void {
    this.salidaLibre = true;
    this.guardarBorrador();
    const esNumero = /^\d{6,}$/.test(texto);
    this.router.navigate(['/dashboard/clientes/nuevo'], {
      queryParams: {
        ...(esNumero ? { documento: texto } : {}),
        returnTo: this.directo ? '/dashboard/ventas/nueva' : `/dashboard/separaciones/${this.idSeparacion}/iniciar-venta`,
      },
    });
  }

  usarConyuge(): void {
    const sep = this.separacion();
    if (!sep) return;
    this.creandoConyuge.set(true);
    this.clienteService.conyugeComoCliente(sep.id_cliente).subscribe({
      next: (c) => {
        this.creandoConyuge.set(false);
        this.agregarComprador(c, 'conyuge');
      },
      error: (err) => {
        this.creandoConyuge.set(false);
        this.toastService.error(err?.error?.detail ?? 'No se pudo cargar al cónyuge');
      },
    });
  }

  // ---- Voucher de la inicial (se inserta en el Contrato Preparatorio) ----

  async onVoucherInicial(event: Event): Promise<void> {
    const input = event.target as HTMLInputElement;
    const archivo = input.files?.[0];
    input.value = '';
    if (!archivo) return;
    if (!['image/jpeg', 'image/png', 'application/pdf'].includes(archivo.type)) {
      this.toastService.error('Formato no permitido (usa JPG, PNG o PDF)');
      return;
    }
    if (archivo.size > 8 * 1024 * 1024) {
      this.toastService.error('El archivo debe pesar menos de 8MB');
      return;
    }
    this.subiendoVoucher.set(true);
    const formData = new FormData();
    formData.append('archivo', await comprimirImagen(archivo));
    this.ventaService.subirArchivo(formData).subscribe({
      next: (res) => {
        this.datosCredito.voucher_url = res.url;
        this.guardarBorrador();
        this.subiendoVoucher.set(false);
      },
      error: (err) => {
        this.subiendoVoucher.set(false);
        this.toastService.error(err?.error?.detail ?? 'No se pudo subir el voucher');
      },
    });
  }

  quitarVoucher(): void {
    this.datosCredito.voucher_url = '';
  }

  // ---- Guardar ----

  mensajeFaltante(): string | null {
    if (!this.precioTotal || this.precioTotal <= 0) return 'Indica el precio total de la venta';
    if (this.formaPago === 'contado') {
      const filas = this.pagosPrevios.filter((p) => p.monto && p.fecha);
      if (filas.length === 0) return 'Registra al menos un pago con su fecha y voucher';
      if (filas.some((p) => !p.voucher_url)) return 'Sube el voucher de cada pago registrado';
      if (this.pagosExcedenPrecio) return 'Los pagos registrados superan el precio total de la venta';
      if ((this.saldoContado ?? 0) > 0 && !this.fechaLimiteSaldo) return 'Indica la fecha límite para pagar el saldo restante';
    }
    if (this.formaPago === 'credito') {
      const dc = this.datosCredito;
      if (!dc.inicial_monto || !dc.fecha_deposito || !dc.numero_operacion.trim()) {
        return 'Completa la inicial, la fecha de inicio de intereses y el N° de operación del crédito';
      }
      if (!dc.voucher_url) return 'Sube el voucher del depósito de la inicial';
      if (this.esPersonalizado) {
        if (this.cuotasValidas().length === 0) return 'Agrega al menos una cuota con fecha al cronograma personalizado';
      } else if (!dc.plazo_meses || dc.plazo_meses < 1) {
        return 'Indica el plazo en meses';
      }
    }
    return null;
  }

  guardar(): void {
    const faltante = this.mensajeFaltante();
    if (faltante) {
      this.error.set(faltante);
      this.irA('vf-inicio');
      return;
    }
    if (!this.separacion()) return;

    this.error.set(null);
    this.guardando.set(true);

    // Se evalúa de nuevo en el servidor para no depender de una vista previa desactualizada
    this.evaluarServidor(this.armarPayload(false)).subscribe({
      next: (ev) => (ev.requiere_autorizacion && !this.omitirAutorizacion ? this.pedirAutorizacion() : this.crear()),
      error: (err) => this.fallo(err, 'No se pudo validar las condiciones'),
    });
  }

  private crear(): void {
    const payload = this.armarPayload(false);
    const llamada = this.directo
      ? this.ventaService.crearDirecta(payload)
      : this.ventaService.crearDesdeSeparacion(this.idSeparacion, payload);
    llamada.subscribe({
      next: (venta) => {
        this.guardando.set(false);
        this.finalizarBorradores();
        this.toastService.exito('Venta iniciada correctamente');
        this.router.navigate(['/dashboard/contratos/venta', venta.id]);
      },
      error: (err) => this.fallo(err, 'No se pudo iniciar la venta'),
    });
  }

  private pedirAutorizacion(): void {
    const payload = this.armarPayload(false);
    if (this.directo) {
      this.ventaService.solicitarAutorizacionDirecta(payload).subscribe({
        next: () => {
          this.guardando.set(false);
          this.toastService.exito('Solicitud enviada a gerencia. Cuando la apruebe, créala desde esta pantalla.');
          this.cargarAutorizaciones();
        },
        error: (err) => this.fallo(err, 'No se pudo solicitar la autorización'),
      });
      return;
    }
    this.ventaService.solicitarAutorizacion(this.idSeparacion, payload).subscribe({
      next: () => {
        this.guardando.set(false);
        this.finalizarBorradores();
        this.toastService.exito('Solicitud enviada a gerencia. Te avisaremos cuando la resuelva.');
        this.router.navigate(['/dashboard/separaciones', this.idSeparacion]);
      },
      error: (err) => this.fallo(err, 'No se pudo solicitar la autorización'),
    });
  }

  private fallo(err: any, porDefecto: string): void {
    this.guardando.set(false);
    const detalle = err?.error?.detail;
    const mensaje = typeof detalle === 'string' ? detalle : porDefecto;
    this.error.set(mensaje);
    this.toastService.error(mensaje);
    this.irA('vf-inicio');
  }

  cancelar(): void {
    // Con cambios: preguntar qué hacer con el borrador
    if (this.separacion() && this.tieneCambiosSinGuardar()) {
      this.confirmarSalida.set(true);
      return;
    }
    // Sin cambios: salir limpio, sin dejar borrador fantasma
    this.descartarTodo();
    this.irSalida();
  }

  /** Lo llama el guard de ruta: abre el modal y espera la decisión */
  confirmarSalidaGuard(): Promise<boolean> {
    return new Promise<boolean>((resolve) => {
      this.resolverGuard = resolve;
      this.confirmarSalida.set(true);
    });
  }

  resolverSalida(accion: 'seguir' | 'guardar' | 'descartar'): void {
    this.confirmarSalida.set(false);
    const respuestaGuard = this.resolverGuard;
    this.resolverGuard = null;

    if (accion === 'seguir') {
      respuestaGuard?.(false); // el guard cancela la navegación y te quedas aquí
      return;
    }

    if (accion === 'guardar') {
      if (this.directo) this.guardarSeleccion();
      this.guardarBorrador(true);
    } else {
      this.descartarTodo();
    }

    this.salidaLibre = true; // para que el guard no vuelva a preguntar
    if (respuestaGuard) respuestaGuard(true); // continúa hacia donde ibas (menú, atrás, etc.)
    else this.irSalida(); // venías del botón Volver/Cancelar
  }

  private descartarTodo(): void {
    this.descartando = true;
    if (this.separacion()) this.borrador.borrar(this.claveBorrador());
    if (this.directo) this.borrador.borrar(this.CLAVE_SEL);
  }

  private irSalida(): void {
    this.salidaLibre = true;
    this.router.navigate(this.directo ? ['/dashboard/contratos'] : ['/dashboard/separaciones', this.idSeparacion]);
  }
}