import { CommonModule } from '@angular/common';
import { Component, HostListener, OnDestroy, OnInit, computed, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { ApiService } from '../../core/services/api.service';
import { ContratoService } from '../../core/services/contrato.service';
import { SocketService } from '../../core/services/socket.service';
import { AuthService } from '../../core/services/auth.service';
import { VentaService } from '../../core/services/venta.service';
import { CobranzaService } from '../../core/services/cobranza.service';
import { ToastService } from '../../core/services/toast.service';
import { ActivatedRoute, Router } from '@angular/router';
import {
  Proyecto,
  Lote,
  Contrato,
  ContratoCreate,
  ContratoClienteInfo,
  CronogramaCuota,
  Pago,
  PagoCreate,
  CotizacionAmortizacion,
  FormaPago,
  Venta,
  DocumentoUbicacion,
} from '../../core/models';

interface ResumenContrato {
  totalPagado: number;
  saldoPendiente: number;
  cuotasPagadas: number;
  cuotasPendientes: number;
  cuotasVencidas: number;
  interesTotal: number;
  proximaFecha: string | null;
}

/** Una fila del cronograma ya calculada: capital, amortización e intereses */
interface FilaCrono {
  c: CronogramaCuota;
  paga: boolean;
  capital: number;
  amortizacion: number;
  acumulado: number;
  cuota: number;
  interesMensual: number;
}

@Component({
  selector: 'app-contratos-list',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './contratos-list.component.html',
  styleUrl: './contratos-list.component.css',
})
export class ContratosListComponent implements OnInit, OnDestroy {
  proyectos = signal<Proyecto[]>([]);
  idProyectoSeleccionado: number | null = null;

  contratos = signal<Contrato[]>([]);
  lotesLibres = signal<Lote[]>([]);
  cargando = signal(false);

    // ---- Filtro por fase documental ----
  faseFiltro = signal<string>('todas');
  readonly fases = [
    { clave: 'todas', etiqueta: 'Todos' },
    { clave: 'iniciada', etiqueta: 'Iniciada' },
    { clave: 'documento_generado', etiqueta: 'Doc. generado' },
    { clave: 'documento_firmado', etiqueta: 'Firmado' },
    { clave: 'escriturada', etiqueta: 'Escriturada' },
    { clave: 'titulada', etiqueta: 'Titulada' },
    { clave: 'finalizada', etiqueta: 'Finalizada' },
  ];

  // ---- Filtro por tipo de documento base (contado = Minuta, crédito = Contrato preparatorio) ----
  formaFiltro = signal<'todas' | 'contado' | 'credito'>('todas');

  contratosFiltrados = computed(() => {
    const f = this.faseFiltro();
    const forma = this.formaFiltro();
    return this.contratos().filter(
      (c) => (f === 'todas' || c.fase_documental === f) && (forma === 'todas' || c.forma_pago === forma)
    );
  });

  kpis = computed(() => {
    const todos = this.contratos();
    return {
      total: todos.length,
      minuta: todos.filter((c) => c.forma_pago === 'contado').length,
      preparatorio: todos.filter((c) => c.forma_pago === 'credito').length,
    };
  });

  conteoFases = computed(() => {
    const m: Record<string, number> = { todas: this.contratos().length };
    for (const c of this.contratos()) {
      if (!c.fase_documental) continue; // sin venta: no pertenece a ninguna fase
      m[c.fase_documental] = (m[c.fase_documental] ?? 0) + 1;
    }
    return m;
  });

  // ---- Drawer de detalle ----
  drawerAbierto = signal(false);
  contratoDrawer = signal<Contrato | null>(null);
  cronogramaPorContrato = signal<Partial<Record<number, CronogramaCuota[]>>>({});
  pagosPorContrato = signal<Partial<Record<number, Pago[]>>>({});
  cargandoCronograma = signal<number | null>(null);
  detalleMensual = signal<Record<number, boolean>>({});
  ventaPorContrato = signal<Partial<Record<number, Venta | null>>>({});
  procesandoCobranza = signal(false);
  private idAbrirPendiente: number | null = null;
  private volverACobranza = false;

  modalComprobanteAbierto = signal(false);
  comprobanteUrlActual = signal<string | null>(null);

  // ---- Modal nuevo contrato ----
  modalAbierto = signal(false);
  guardando = signal(false);
  error = signal<string | null>(null);

  numeroContrato = '';
  idLote: number | null = null;
  fechaContrato = new Date().toISOString().slice(0, 10);
  formaPago: FormaPago = 'contado';
  frecuenciaCuota: 'mensual' | 'anual' = 'mensual';
  precioTotal: number | null = null;
  inicialAbonado = 0;
  fechaAbono = '';
  numeroCuotas: number | null = null;
  tieneInteres = false;
  tem: number | null = null;
  fechaInicioInteres = '';
  tipoContrato = '';
  observaciones = '';

  tipoDocumento = 'DNI';
  numeroDocumento = '';
  nombresCliente = '';
  apellidosCliente = '';
  correoCliente = '';
  telefonoCliente = '';
  direccionCliente = '';

  // ---- Modal registrar pago ----
  modalPagoAbierto = signal(false);
  guardandoPago = signal(false);
  errorPago = signal<string | null>(null);
  contratoPagoId: number | null = null;
  cuotaSeleccionada: CronogramaCuota | null = null;
  montoPago: number | null = null;
  fechaPago = new Date().toISOString().slice(0, 10);
  metodoPago = 'efectivo';
  numeroOperacion = '';
  observacionPago = '';
  archivoComprobante: File | null = null;

  get saldoFinanciado(): number {
    const precio = this.precioTotal ?? 0;
    const inicial = this.inicialAbonado ?? 0;
    return Math.max(precio - inicial, 0);
  }

  get plazoTotalMeses(): number {
    const cuotas = this.numeroCuotas ?? 0;
    return this.frecuenciaCuota === 'anual' ? cuotas * 12 : cuotas;
  }

  constructor(
    private api: ApiService,
    private contratoService: ContratoService,
    private socket: SocketService,
    private auth: AuthService,
    private ventaService: VentaService,
    private cobranzaService: CobranzaService,
    private toastService: ToastService,
    private route: ActivatedRoute,
    private router: Router
  ) {}

  get puedeGestionarCobranza(): boolean {
    return ['admin', 'gerencia', 'cobranza'].includes(this.auth.usuario()?.rol?.clave ?? '');
  }

  ngOnInit(): void {
    const abrir = Number(this.route.snapshot.queryParamMap.get('abrir'));
    this.idAbrirPendiente = abrir || null;
    this.volverACobranza = this.route.snapshot.queryParamMap.get('origen') === 'cobranza';

    this.api.get<Proyecto[]>('/proyectos').subscribe((proyectos) => {
      this.proyectos.set(proyectos);
      if (proyectos.length > 0) {
        this.idProyectoSeleccionado = proyectos[0].id;
        this.cambiarProyecto();
      }
    });

    this.socket.conectar();
    this.socket.onEvento.subscribe((evento) => {
      if (evento.evento === 'contrato:nuevo') {
        const contrato = evento.data as Contrato;
        if (contrato && contrato.id_proyecto === this.idProyectoSeleccionado) {
          this.cargarContratos(true);
          this.cargarLotesLibres();
        }
      }
      if (evento.evento === 'contrato:pago_registrado') {
        const idContrato = (evento.data as any)?.id_contrato;
        this.cargarContratos(true);
        if (idContrato && this.contratoDrawer()?.id === idContrato) {
          this.cargarCronograma(idContrato);
          this.cargarVenta(idContrato);
        }
      }
      if (evento.evento === 'venta:nueva' || evento.evento === 'venta:actualizada') {
        this.cargarContratos(true); // refresca conteos y burbujas en vivo
        const abierto = this.contratoDrawer();
        if (abierto) this.cargarVenta(abierto.id);
      }
    });
  }

  ngOnDestroy(): void {
    this.socket.desconectar();
  }

  cambiarProyecto(): void {
    if (!this.idProyectoSeleccionado) return;
    this.cargarContratos();
    this.cargarLotesLibres();
  }

  cargarContratos(silencioso = false): void {
    if (!this.idProyectoSeleccionado) return;
    if (!silencioso) this.cargando.set(true);
    this.contratoService.listar(this.idProyectoSeleccionado).subscribe({
      next: (res) => {
        this.contratos.set(res);
        this.cargando.set(false);

        const abierto = this.contratoDrawer();
        if (abierto) {
          const actualizado = res.find((c) => c.id === abierto.id);
          if (actualizado) this.contratoDrawer.set(actualizado);
        }
        if (this.idAbrirPendiente) {
          const buscado = res.find((c) => c.id === this.idAbrirPendiente);
          this.idAbrirPendiente = null;
          if (buscado) this.abrirDrawer(buscado);
        }
      },
      error: () => this.cargando.set(false),
    });
  }

  cargarLotesLibres(): void {
    if (!this.idProyectoSeleccionado) return;
    this.api.get<Lote[]>('/lotes', { id_proyecto: this.idProyectoSeleccionado }).subscribe((lotes) => {
      this.lotesLibres.set(lotes.filter((l) => l.estado === 'libre'));
    });
  }

  // ---- Drawer ----

  abrirDrawer(contrato: Contrato): void {
    this.contratoDrawer.set(contrato);
    this.drawerAbierto.set(true);
    if (!this.cronogramaPorContrato()[contrato.id]) {
      this.cargarCronograma(contrato.id);
    }
    this.cargarVenta(contrato.id);
  }

  cargarVenta(idContrato: number): void {
    this.ventaService.ventaDeContrato(idContrato).subscribe({
      next: (r) => {
        if (!r.id_venta) {
          this.ventaPorContrato.update((a) => ({ ...a, [idContrato]: null }));
          return;
        }
        this.ventaService.obtener(r.id_venta).subscribe({
          next: (v) => this.ventaPorContrato.update((a) => ({ ...a, [idContrato]: v })),
          error: () => this.ventaPorContrato.update((a) => ({ ...a, [idContrato]: null })),
        });
      },
      error: () => this.ventaPorContrato.update((a) => ({ ...a, [idContrato]: null })),
    });
  }

  abrirVenta(idVenta: number): void {
    this.router.navigate(['/dashboard/contratos/venta', idVenta]);
  }

  recalcularCuotas(contrato: Contrato): void {
    if (!confirm('¿Recalcular las cuotas pendientes con el saldo actual?')) return;
    this.procesandoCobranza.set(true);
    this.cobranzaService.recalcular(contrato.id).subscribe({
      next: (r) => {
        this.procesandoCobranza.set(false);
        this.toastService.exito(r.mensaje);
        this.cargarCronograma(contrato.id);
      },
      error: (err) => {
        this.procesandoCobranza.set(false);
        this.toastService.error(err?.error?.detail ?? 'No se pudo recalcular');
      },
    });
  }

  cancelarContrato(contrato: Contrato): void {
    if (!confirm('¿Cancelar el contrato? Solo es posible si el cliente ya pagó todo el saldo.')) return;
    this.procesandoCobranza.set(true);
    this.cobranzaService.cancelar(contrato.id).subscribe({
      next: () => {
        this.procesandoCobranza.set(false);
        this.toastService.exito('Contrato cancelado');
        this.cargarContratos(true);
        this.cargarCronograma(contrato.id);
      },
      error: (err) => {
        this.procesandoCobranza.set(false);
        this.toastService.error(err?.error?.detail ?? 'No se pudo cancelar el contrato');
      },
    });
  }

  finalizarVenta(contrato: Contrato): void {
    const venta = this.ventaPorContrato()[contrato.id];
    if (!venta) return;
    if (!confirm('¿Finalizar la venta? Esta acción cierra el proceso de cobranza.')) return;
    this.procesandoCobranza.set(true);
    this.cobranzaService.finalizarVenta(venta.id).subscribe({
      next: () => {
        this.procesandoCobranza.set(false);
        this.toastService.exito('Venta finalizada');
        this.cargarVenta(contrato.id);
      },
      error: (err) => {
        this.procesandoCobranza.set(false);
        this.toastService.error(err?.error?.detail ?? 'No se pudo finalizar la venta');
      },
    });
  }

  cerrarDrawer(): void {
    this.drawerAbierto.set(false);
    if (this.volverACobranza) {
      this.router.navigate(['/dashboard/cobranza']);
    }
  }

  get puedeRegistrarPago(): boolean {
    return ['admin', 'gerencia', 'supervisor', 'cobranza', 'contabilidad'].includes(this.auth.usuario()?.rol?.clave ?? '');
  }

  /** ¿Esa cuota ya tiene un pago esperando a Caja o Facturación? */
  pagoEnProceso(idContrato: number, idCuota: number): boolean {
    const cuota = (this.cronogramaPorContrato()[idContrato] ?? []).find((q) => q.id === idCuota);
    return (this.pagosPorContrato()[idContrato] ?? []).some(
      (p) =>
        (p.estado === 'pendiente_caja' || p.estado === 'pendiente_facturacion') &&
        (p.id_cuota === idCuota ||
          (!!cuota && !!p.cuota_desde && cuota.numero_cuota >= p.cuota_desde && cuota.numero_cuota <= (p.cuota_hasta ?? p.cuota_desde)))
    );
  }

  /** El historial guardaba el id interno de la cuota; aquí se muestra su N° en el cronograma. */
  numeroCuota(idContrato: number, idCuota?: number | null): string {
    if (!idCuota) return '—';
    const cuota = (this.cronogramaPorContrato()[idContrato] ?? []).find((q) => q.id === idCuota);
    return cuota ? String(cuota.numero_pago ?? cuota.numero_cuota) : '—';
  }

  /** N° que ve el cliente: en crédito anual el N° interno es el del mes (13, 25...) y aquí se muestra 1, 2, 3... */
  numeroPago(idContrato: number, numeroCuota: number): number {
    const fila = (this.cronogramaPorContrato()[idContrato] ?? []).find((q) => q.numero_cuota === numeroCuota);
    return fila?.numero_pago ?? numeroCuota;
  }
  conceptoPago(p: Pago): string {
    if (p.tipo === 'inicial') return 'Inicial';
    if (p.tipo === 'contado') return 'Pago al contado';
    if (p.tipo === 'amortizacion') {
      const base = p.modalidad === 'amortizar_plazo' ? 'Amortización · reduce plazo' : 'Amortización · baja cuota';
      if (!p.cuota_desde) return base;
      const idc = this.contratoDrawer()!.id;
      const d = this.numeroPago(idc, p.cuota_desde);
      const h = this.numeroPago(idc, p.cuota_hasta ?? p.cuota_desde);
      return `${h !== d ? `Cuotas ${d} a ${h}` : `Cuota ${d}`} + ${base}`;
    }
    if (p.cuota_desde) {
      const idc = this.contratoDrawer()!.id;
      const d = this.numeroPago(idc, p.cuota_desde);
      const h = this.numeroPago(idc, p.cuota_hasta ?? p.cuota_desde);
      return h !== d ? `Cuotas ${d} a ${h}` : `Cuota ${d}`;
    }
    if (p.id_cuota) return this.numeroCuota(this.contratoDrawer()!.id, p.id_cuota);
    return '—';
  }

  etiquetaPago(estado: string): string {
    const mapa: Record<string, string> = {
      pendiente_caja: 'En Caja',
      pendiente_facturacion: 'En Facturación',
      validado: 'Aplicado',
      rechazado: 'Rechazado',
    };
    return mapa[estado] ?? estado;
  }

  cargarCronograma(idContrato: number): void {
    this.cargandoCronograma.set(idContrato);
    this.contratoService.cronograma(idContrato).subscribe({
      next: (cuotas) => {
        this.cronogramaPorContrato.update((actual) => ({ ...actual, [idContrato]: cuotas }));
        this.cargandoCronograma.set(null);
      },
      error: () => this.cargandoCronograma.set(null),
    });

    this.contratoService.listarPagos(idContrato).subscribe({
      next: (pagos) => {
        this.pagosPorContrato.update((actual) => ({ ...actual, [idContrato]: pagos }));
      },
    });
  }

  toggleDetalleMensual(idContrato: number): void {
    this.detalleMensual.update((actual) => ({ ...actual, [idContrato]: !actual[idContrato] }));
  }

  cuotasVisibles(contrato: Contrato): CronogramaCuota[] {
    const todas = this.cronogramaPorContrato()[contrato.id] ?? [];
    if (contrato.frecuencia_cuota === 'anual' && !this.detalleMensual()[contrato.id]) {
      return todas.filter((c) => c.requiere_pago);
    }
    return todas;
  }

  // ---- Cronograma del drawer: capital, amortización e intereses (mismas columnas del simulado) ----

  private num(v: unknown): number | null {
    if (v === null || v === undefined || v === '') return null;
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
  }

  /** Monto financiado del contrato: base del capital y de los totales */
  private financiadoDe(contrato: Contrato): number {
    const guardado = this.num((contrato as any).saldo_financiado);
    if (guardado !== null && guardado > 0) return guardado;
    return Math.max(Number(contrato.precio_total ?? 0) - Number(contrato.inicial_abonado ?? 0), 0);
  }

  /** Abonos a capital ya aplicados: el capital vigente baja en la fecha efectiva de cada uno */
  private amortizacionesDe(idContrato: number): { fe: string; aCapital: number; monto: number }[] {
    return (this.pagosPorContrato()[idContrato] ?? [])
      .filter((p) => p.tipo === 'amortizacion' && p.estado === 'validado' && !!p.detalle_amortizacion)
      .map((p) => ({
        fe: String(p.detalle_amortizacion.fecha_efectiva).slice(0, 10),
        aCapital: Number(p.detalle_amortizacion.a_capital ?? 0),
        monto: Number(p.monto ?? 0),
      }))
      .sort((a, b) => a.fe.localeCompare(b.fe));
  }

  /** Suma de los abonos a capital: se agrega a las cuotas para que los totales de interés cuadren */
  private montoAmortizado(idContrato: number): number {
    return this.amortizacionesDe(idContrato).reduce((acc, a) => acc + a.monto, 0);
  }

  /**
   * Filas que se muestran en el drawer.
   * Capital = vigente ANTES de amortizar; el interés acumulado se reinicia en cada fecha de pago.
   */
  filasDrawer = computed<FilaCrono[]>(() => {
    const ct = this.contratoDrawer();
    if (!ct) return [];
    const todas = (this.cronogramaPorContrato()[ct.id] ?? []) as any[];
    let capital = this.financiadoDe(ct);
    let corrido = 0;
    const anual = ct.frecuencia_cuota === 'anual';
    const abonos = [...this.amortizacionesDe(ct.id)];

    const filas = todas.map((c) => {
      const paga = !!c.requiere_pago;
      const interesMensual = this.num(c.interes_mensual) ?? 0;
      corrido += interesMensual;

      // Después de un abono a capital, el capital vigente baja desde la primera fila posterior a su fecha efectiva
      const fechaFila = String(c.fecha_pago_programada).slice(0, 10);
      while (abonos.length && abonos[0].fe < fechaFila) {
        capital = Math.max(Math.round((capital - abonos.shift()!.aCapital) * 100) / 100, 0);
      }

      // Anual: interés acumulado del período (se reinicia en cada pago). Resto de frecuencias: interés de esa cuota.
      const acumulado = anual ? (this.num(c.interes_acumulado) ?? corrido) : interesMensual;
      const cuota = paga ? Number(c.monto_cuota ?? 0) : 0;
      const amortizacion = paga ? (this.num(c.amortizacion) ?? Math.max(cuota - acumulado, 0)) : 0;

      const fila: FilaCrono = { c, paga, capital, amortizacion, acumulado, cuota, interesMensual };

      if (paga) corrido = 0;
      capital = Math.max(Math.round((capital - amortizacion) * 100) / 100, 0);
      return fila;
    });

    const soloPagos = ct.frecuencia_cuota === 'anual' && !this.detalleMensual()[ct.id];
    return soloPagos ? filas.filter((f) => f.paga) : filas;
  });

  /** Totales como en el Excel: amortización = monto financiado, interés = cuotas - financiado */
  totalesDrawer = computed(() => {
    const ct = this.contratoDrawer();
    if (!ct) return { amortizacion: 0, interes: 0, cuota: 0 };
    const r = (n: number) => Math.round(n * 100) / 100;
    const financiado = this.financiadoDe(ct);
    const cuota = r(
      (this.cronogramaPorContrato()[ct.id] ?? [])
        .filter((c) => c.requiere_pago)
        .reduce((acc, c) => acc + Number(c.monto_cuota ?? 0), 0) + this.montoAmortizado(ct.id)
    );
    return { amortizacion: r(financiado), interes: r(Math.max(cuota - financiado, 0)), cuota };
  });

  fmtFecha(f: string | null | undefined): string {
    if (!f) return '—';
    const [y, m, d] = String(f).slice(0, 10).split('-');
    return d && m && y ? `${d}/${m}/${y}` : String(f);
  }

  resumen(contrato: Contrato): ResumenContrato {
    const cuotas = (this.cronogramaPorContrato()[contrato.id] ?? []).filter((c) => c.requiere_pago);
    const pagos = (this.pagosPorContrato()[contrato.id] ?? []).filter(
      (p) => p.estado === 'validado' && p.tipo !== 'inicial' && p.tipo !== 'contado'
    );

    const totalPagado = pagos.reduce((acc, p) => acc + Number(p.monto), 0);
    const totalCuotas = cuotas.reduce((acc, c) => acc + Number(c.monto_cuota), 0) + this.montoAmortizado(contrato.id);
    const saldoPendiente = Math.max(totalCuotas - totalPagado, 0);
    const cuotasPagadas = cuotas.filter((c) => c.estado === 'pagada').length;
    const cuotasPendientes = cuotas.filter((c) => c.estado === 'pendiente' || c.estado === 'parcial').length;
    const cuotasVencidas = cuotas.filter((c) => c.estado === 'vencida').length;
    const interesTotal = Math.max(Math.round((totalCuotas - this.financiadoDe(contrato)) * 100) / 100, 0);
    const proxima = cuotas.find((c) => c.estado !== 'pagada');

    return {
      totalPagado,
      saldoPendiente,
      cuotasPagadas,
      cuotasPendientes,
      cuotasVencidas,
      interesTotal,
      proximaFecha: proxima ? proxima.fecha_pago_programada : null,
    };
  }

  urlCompleta(relativa?: string): string | null {
    if (!relativa) return null;
    if (relativa.startsWith('http://') || relativa.startsWith('https://')) return relativa;
    return this.api.apiUrl + relativa;
  }
  
  esImagen(url: string): boolean {
    return /\.(jpg|jpeg|png)$/i.test(url);
  }

  abrirComprobante(relativa?: string): void {
    const url = this.urlCompleta(relativa);
    if (!url) return;
    this.comprobanteUrlActual.set(url);
    this.modalComprobanteAbierto.set(true);
  }


    verVenta(c: Contrato, event: Event): void {
    event.stopPropagation(); // no abrir el drawer
    if (c.id_venta) this.abrirVenta(c.id_venta);
  }

  etiquetaTramite(t?: string | null): string {
    const mapa: Record<string, string> = { pendiente: 'Pendiente', en_proceso: 'En proceso', concretado: 'Concretado' };
    return t ? (mapa[t] ?? t) : '';
  }

  etiquetaUbic(u: DocumentoUbicacion): string {
    const mapa: Record<string, string> = {
      notaria: 'Notaría', juez_de_paz: 'Juez de Paz', municipalidad: 'Municipalidad',
      archivo_central: 'Archivo Central', otro: 'Otro',
    };
    const base = mapa[u.ubicacion] ?? u.ubicacion;
    return u.notaria_nombre ? `${base} (${u.notaria_nombre})` : base;
  }

  /** Los 4 documentos de la venta con su archivo, ubicación y estado de trámite */
  documentosVenta(v: Venta) {
    const ub = new Map(this.ubicacionesActuales(v).map((u) => [u.tipo_documento, u]));
    const contado = v.forma_pago === 'contado';
    const defs = [
      { clave: contado ? 'minuta' : 'contrato_preparatorio', etiqueta: contado ? 'Minuta' : 'Contrato Preparatorio', url: v.documento_generado_url },
      { clave: 'firmado', etiqueta: 'Documento firmado', url: v.documento_firmado_url },
      { clave: 'escritura', etiqueta: 'Escritura pública', url: v.escritura_url },
      { clave: 'titulo', etiqueta: 'Título de propiedad', url: v.titulo_url },
    ];
    return defs.map((d) => {
      const u = ub.get(d.clave);
      return { ...d, hecho: !!d.url, ubicacion: u ? this.etiquetaUbic(u) : null, tramite: u?.estado_tramite ?? null };
    });
  }

  /** Checklist de documentos de un contrato, según la fase de su venta */
  pasosDoc(c: Contrato): { etiqueta: string; hecho: boolean }[] {
    const f = c.fase_documental;
    if (!f || f === 'cancelada' || f === 'anulada') return [];
    const niveles: Record<string, number> = {
      iniciada: 0, documento_generado: 1, documento_firmado: 2,
      escriturada: 3, titulada: 4, finalizada: 4,
    };
    const nivel = niveles[f] ?? 0;
    const etiquetas = [
      c.forma_pago === 'contado' ? 'Minuta' : 'Contrato prep.',
      'Firmado',
      'Escritura pública',
      'Título',
    ];
    return etiquetas.map((etiqueta, i) => ({ etiqueta, hecho: i < nivel }));
  }


  nombreDocBase(c: Contrato): string {
    return c.forma_pago === 'contado' ? 'Minuta' : 'Contrato prep.';
  }

  etiquetaFase(f?: string | null): string {
    if (!f) return 'Sin venta';
    if (f === 'cancelada') return 'Cancelada';
    if (f === 'anulada') return 'Anulada';
    return this.fases.find((x) => x.clave === f)?.etiqueta ?? f;
  }

  /** Último registro por tipo de documento (evita duplicados en el drawer) */
  ubicacionesActuales(venta: Venta): DocumentoUbicacion[] {
    const m = new Map<string, DocumentoUbicacion>();
    for (const u of [...venta.ubicaciones].sort((a, b) => a.id - b.id)) m.set(u.tipo_documento, u);
    return [...m.values()];
  }
  clienteTitular(contrato: Contrato): ContratoClienteInfo | undefined {
    return contrato.clientes[0];
  }

  cerrarComprobante(): void {
    this.modalComprobanteAbierto.set(false);
    this.comprobanteUrlActual.set(null);
  }

  @HostListener('document:keydown.escape')
  onEscape(): void {
    if (this.modalComprobanteAbierto()) {
      this.cerrarComprobante();
      return;
    }
    if (this.modalVariasAbierto()) {
      this.cerrarModalVarias();
      return;
    }
    if (this.modalPagoAbierto()) {
      this.cerrarModalPago();
      return;
    }
    if (this.modalAbierto()) {
      this.cerrarModal();
      return;
    }
    if (this.drawerAbierto()) {
      this.cerrarDrawer();
    }
  }

  // ---- Nuevo contrato ----

  abrirNuevoContrato(): void {
    this.numeroContrato = '';
    this.idLote = null;
    this.fechaContrato = new Date().toISOString().slice(0, 10);
    this.formaPago = 'contado';
    this.frecuenciaCuota = 'mensual';
    this.precioTotal = null;
    this.inicialAbonado = 0;
    this.fechaAbono = '';
    this.numeroCuotas = null;
    this.tieneInteres = false;
    this.tem = null;
    this.fechaInicioInteres = '';
    this.tipoContrato = '';
    this.observaciones = '';
    this.tipoDocumento = 'DNI';
    this.numeroDocumento = '';
    this.nombresCliente = '';
    this.apellidosCliente = '';
    this.correoCliente = '';
    this.telefonoCliente = '';
    this.direccionCliente = '';
    this.error.set(null);
    this.modalAbierto.set(true);
  }

  onLoteSeleccionado(): void {
    const lote = this.lotesLibres().find((l) => l.id === this.idLote);
    if (!lote) return;
    this.precioTotal =
      this.formaPago === 'contado'
        ? Number(lote.precio_total_contado ?? lote.precio_total_base ?? 0)
        : Number(lote.precio_total_financiado ?? lote.precio_total_base ?? 0);
  }

  onFormaPagoChange(): void {
    this.onLoteSeleccionado();
  }

  cerrarModal(): void {
    this.modalAbierto.set(false);
  }

  guardarContrato(): void {
    if (!this.idProyectoSeleccionado || !this.idLote || !this.numeroContrato || !this.precioTotal) {
      this.error.set('Completa lote, número de contrato y precio total');
      return;
    }
    if (!this.numeroDocumento || !this.nombresCliente || !this.apellidosCliente) {
      this.error.set('Completa los datos del cliente titular');
      return;
    }
    if (this.formaPago === 'credito' && (!this.numeroCuotas || this.numeroCuotas <= 0)) {
      this.error.set('Indica el número de cuotas para un crédito');
      return;
    }

    const payload: ContratoCreate = {
      numero_contrato: this.numeroContrato,
      id_lote: this.idLote,
      fecha_contrato: this.fechaContrato,
      precio_total: this.precioTotal,
      inicial_abonado: this.inicialAbonado || 0,
      fecha_abono: this.fechaAbono || undefined,
      tiene_interes: this.formaPago === 'credito' ? this.tieneInteres : false,
      forma_pago: this.formaPago,
      frecuencia_cuota: this.formaPago === 'credito' ? this.frecuenciaCuota : 'mensual',
      saldo_financiado: this.formaPago === 'credito' ? this.saldoFinanciado : 0,
      numero_cuotas: this.formaPago === 'credito' ? this.numeroCuotas! : 0,
      tem: this.tieneInteres ? this.tem ?? undefined : undefined,
      fecha_inicio_interes: this.tieneInteres ? this.fechaInicioInteres || undefined : undefined,
      tipo_contrato: this.tipoContrato || undefined,
      observaciones: this.observaciones || undefined,
      clientes: [
        {
          rol: 'titular',
          cliente_nuevo: {
            tipo_documento: this.tipoDocumento,
            numero_documento: this.numeroDocumento,
            nombres: this.nombresCliente,
            apellidos: this.apellidosCliente,
            correo: this.correoCliente || undefined,
            telefono: this.telefonoCliente || undefined,
            direccion: this.direccionCliente || undefined,
          },
        },
      ],
    };

    this.guardando.set(true);
    this.error.set(null);

    this.contratoService.crear(payload).subscribe({
      next: () => {
        this.guardando.set(false);
        this.modalAbierto.set(false);
        this.cargarContratos();
        this.cargarLotesLibres();
      },
      error: (err) => {
        this.guardando.set(false);
        this.error.set(err?.error?.detail ?? 'Error al crear el contrato');
      },
    });
  }

  // ---- Registrar pago ----

  abrirRegistrarPago(idContrato: number, cuota: CronogramaCuota): void {
    this.contratoPagoId = idContrato;
    this.cuotaSeleccionada = cuota;
    this.montoPago = Number(cuota.monto_cuota) - Number(cuota.monto_pagado ?? 0);
    this.fechaPago = new Date().toISOString().slice(0, 10);
    this.metodoPago = 'efectivo';
    this.numeroOperacion = '';
    this.observacionPago = '';
    this.archivoComprobante = null;
    this.errorPago.set(null);
    this.modalPagoAbierto.set(true);
  }

  cerrarModalPago(): void {
    this.modalPagoAbierto.set(false);
  }

  // ---- Pagar varias cuotas ----
  modalVariasAbierto = signal(false);
  cuotasAPagar: number | null = null;

  pendientesDe(idContrato: number): CronogramaCuota[] {
    return (this.cronogramaPorContrato()[idContrato] ?? [])
      .filter((c) => c.requiere_pago && c.estado !== 'pagada')
      .sort((a, b) => a.numero_cuota - b.numero_cuota);
  }

  get seleccionVarias(): { cuotas: CronogramaCuota[]; total: number; desde: number; hasta: number } | null {
    const id = this.contratoDrawer()?.id;
    const n = Number(this.cuotasAPagar) || 0;
    if (!id || n < 1) return null;
    const cuotas = this.pendientesDe(id).slice(0, n);
    if (cuotas.length === 0) return null;
    const total = cuotas.reduce((a, c) => a + (Number(c.monto_cuota) - Number(c.monto_pagado ?? 0)), 0);
    return {
      cuotas,
      total,
      desde: cuotas[0].numero_pago ?? cuotas[0].numero_cuota,
      hasta: cuotas[cuotas.length - 1].numero_pago ?? cuotas[cuotas.length - 1].numero_cuota,
    };
  }

  abrirPagarVarias(idContrato: number): void {
    this.contratoPagoId = idContrato;
    this.cuotasAPagar = Math.min(2, this.pendientesDe(idContrato).length);
    this.fechaPago = new Date().toISOString().slice(0, 10);
    this.metodoPago = 'transferencia';
    this.numeroOperacion = '';
    this.observacionPago = '';
    this.archivoComprobante = null;
    this.errorPago.set(null);
    this.modalVariasAbierto.set(true);
  }

  cerrarModalVarias(): void {
    this.modalVariasAbierto.set(false);
  }

  guardarPagoVarias(): void {
    const sel = this.seleccionVarias;
    if (!this.contratoPagoId || !sel) {
      this.errorPago.set('Indica cuántas cuotas va a pagar');
      return;
    }
    if (!this.archivoComprobante) {
      this.errorPago.set('Debes adjuntar el comprobante de pago (imagen o PDF)');
      return;
    }
    this.guardandoPago.set(true);
    this.errorPago.set(null);

    const formData = new FormData();
    formData.append('archivo', this.archivoComprobante);

    this.contratoService.subirComprobante(formData).subscribe({
      next: (res) => {
        const payload: PagoCreate = {
          cantidad_cuotas: sel.cuotas.length,
          monto: Math.round(sel.total * 100) / 100,
          fecha_pago: this.fechaPago,
          metodo_pago: this.metodoPago,
          numero_operacion: this.numeroOperacion || undefined,
          observacion: this.observacionPago || undefined,
          comprobante_url: res.url,
        };
        this.contratoService.registrarPago(this.contratoPagoId!, payload).subscribe({
          next: () => {
            this.guardandoPago.set(false);
            this.modalVariasAbierto.set(false);
            this.toastService.exito('Pago enviado a Caja para su validación');
            this.cargarCronograma(this.contratoPagoId!);
          },
          error: (err) => {
            this.guardandoPago.set(false);
            this.errorPago.set(err?.error?.detail ?? 'Error al registrar el pago');
          },
        });
      },
      error: (err) => {
        this.guardandoPago.set(false);
        this.errorPago.set(err?.error?.detail ?? 'Error al subir el comprobante');
      },
    });
  }

  // ---- Amortizar capital (solo contratos con interés) ----
  modalAmortAbierto = signal(false);
  cotizandoAmort = signal(false);
  cotizacion = signal<CotizacionAmortizacion | null>(null);
  private cotizacionClave = '';
  modalidadAmort: 'amortizar_cuota' | 'amortizar_plazo' = 'amortizar_cuota';
  montoAmort: number | null = null;

  toNum(v: unknown): number {
    return Number(v ?? 0);
  }

  /** ¿Ya hay una amortización esperando a Caja o Facturación? */
  amortizacionEnProceso(idContrato: number): boolean {
    return (this.pagosPorContrato()[idContrato] ?? []).some(
      (p) => p.tipo === 'amortizacion' && (p.estado === 'pendiente_caja' || p.estado === 'pendiente_facturacion')
    );
  }

  private claveAmort(): string {
    return `${this.montoAmort}|${this.fechaPago}|${this.modalidadAmort}`;
  }

  /** La cotización en pantalla corresponde a lo que está escrito ahora */
  get cotizacionVigente(): boolean {
    return !!this.cotizacion() && this.cotizacionClave === this.claveAmort();
  }

  abrirAmortizar(idContrato: number): void {
    this.contratoPagoId = idContrato;
    this.modalidadAmort = 'amortizar_cuota';
    this.montoAmort = null;
    this.cotizacion.set(null);
    this.cotizacionClave = '';
    this.fechaPago = new Date().toISOString().slice(0, 10);
    this.metodoPago = 'transferencia';
    this.numeroOperacion = '';
    this.observacionPago = '';
    this.archivoComprobante = null;
    this.errorPago.set(null);
    this.modalAmortAbierto.set(true);
  }

  cerrarModalAmort(): void {
    this.modalAmortAbierto.set(false);
  }

  cotizarAmort(): void {
    if (!this.contratoPagoId || !this.montoAmort || this.montoAmort <= 0) {
      this.errorPago.set('Indica cuánto va a abonar el cliente');
      return;
    }
    this.errorPago.set(null);
    this.cotizacion.set(null);
    this.cotizandoAmort.set(true);
    const clave = this.claveAmort();
    this.contratoService
      .cotizarAmortizacion(this.contratoPagoId, {
        monto: this.montoAmort,
        fecha_pago: this.fechaPago,
        modalidad: this.modalidadAmort,
      })
      .subscribe({
        next: (c) => {
          this.cotizacion.set(c);
          this.cotizacionClave = clave;
          this.cotizandoAmort.set(false);
        },
        error: (err) => {
          this.cotizandoAmort.set(false);
          this.errorPago.set(err?.error?.detail ?? 'No se pudo calcular la amortización');
        },
      });
  }

  guardarAmortizacion(): void {
    if (!this.contratoPagoId || !this.montoAmort || !this.cotizacionVigente) {
      this.errorPago.set('Calcula la amortización antes de confirmar');
      return;
    }
    if (!this.archivoComprobante) {
      this.errorPago.set('Debes adjuntar el comprobante de pago (imagen o PDF)');
      return;
    }
    this.guardandoPago.set(true);
    this.errorPago.set(null);

    const formData = new FormData();
    formData.append('archivo', this.archivoComprobante);

    this.contratoService.subirComprobante(formData).subscribe({
      next: (res) => {
        const payload: PagoCreate = {
          modalidad: this.modalidadAmort,
          monto: Math.round(this.montoAmort! * 100) / 100,
          fecha_pago: this.fechaPago,
          metodo_pago: this.metodoPago,
          numero_operacion: this.numeroOperacion || undefined,
          observacion: this.observacionPago || undefined,
          comprobante_url: res.url,
        };
        this.contratoService.registrarPago(this.contratoPagoId!, payload).subscribe({
          next: () => {
            this.guardandoPago.set(false);
            this.modalAmortAbierto.set(false);
            this.toastService.exito('Amortización enviada a Caja para su validación');
            this.cargarCronograma(this.contratoPagoId!);
          },
          error: (err) => {
            this.guardandoPago.set(false);
            this.errorPago.set(err?.error?.detail ?? 'Error al registrar la amortización');
          },
        });
      },
      error: (err) => {
        this.guardandoPago.set(false);
        this.errorPago.set(err?.error?.detail ?? 'Error al subir el comprobante');
      },
    });
  }

  onArchivoSeleccionado(event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0] ?? null;
    if (!file) {
      this.archivoComprobante = null;
      return;
    }

    const tiposPermitidos = ['image/jpeg', 'image/png', 'application/pdf'];
    if (!tiposPermitidos.includes(file.type)) {
      this.errorPago.set('Solo se permiten archivos JPG, PNG o PDF');
      this.archivoComprobante = null;
      return;
    }
    if (file.size > 8 * 1024 * 1024) {
      this.errorPago.set('El archivo no debe superar los 8MB');
      this.archivoComprobante = null;
      return;
    }

    this.errorPago.set(null);
    this.archivoComprobante = file;
  }

  guardarPago(): void {
    if (!this.contratoPagoId || !this.cuotaSeleccionada || !this.montoPago || this.montoPago <= 0) {
      this.errorPago.set('Indica un monto válido');
      return;
    }
    if (!this.archivoComprobante) {
      this.errorPago.set('Debes adjuntar el comprobante de pago (imagen o PDF)');
      return;
    }

    this.guardandoPago.set(true);
    this.errorPago.set(null);

    const formData = new FormData();
    formData.append('archivo', this.archivoComprobante);

    this.contratoService.subirComprobante(formData).subscribe({
      next: (res) => {
        const payload: PagoCreate = {
          id_cuota: this.cuotaSeleccionada!.id,
          monto: this.montoPago!,
          fecha_pago: this.fechaPago,
          metodo_pago: this.metodoPago,
          numero_operacion: this.numeroOperacion || undefined,
          observacion: this.observacionPago || undefined,
          comprobante_url: res.url,
        };

        this.contratoService.registrarPago(this.contratoPagoId!, payload).subscribe({
          next: () => {
            this.guardandoPago.set(false);
            this.modalPagoAbierto.set(false);
            this.toastService.exito('Pago enviado a Caja para su validación');
            this.cargarCronograma(this.contratoPagoId!);
          },
          error: (err) => {
            this.guardandoPago.set(false);
            this.errorPago.set(err?.error?.detail ?? 'Error al registrar el pago');
          },
        });
      },
      error: (err) => {
        this.guardandoPago.set(false);
        this.errorPago.set(err?.error?.detail ?? 'Error al subir el comprobante');
      },
    });
  }
}