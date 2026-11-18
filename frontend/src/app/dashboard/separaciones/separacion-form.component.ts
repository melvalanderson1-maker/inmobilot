import { CommonModule } from '@angular/common';
import { Component, HostListener, OnInit, computed, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';

import { ApiService } from '../../core/services/api.service';
import { ClienteService } from '../../core/services/cliente.service';
import { ProformaService } from '../../core/services/proforma.service';
import { SeparacionService } from '../../core/services/separacion.service';
import { ToastService } from '../../core/services/toast.service';
import { Cliente, FormaPago, Lote, Manzana, Proforma } from '../../core/models';
import { ClienteBuscadorComponent } from '../../shared/cliente-buscador/cliente-buscador.component';
import { BorradorService } from '../../core/services/borrador.service';




type FormSeparacion = {
  id_lote: number | null;
  fecha_inicio: string;
  fecha_vencimiento: string;
  importe: number | null;
  motivo: string;
  tipo_pago: FormaPago | null;
  notas: string;
  agenda_fecha: string;
  voucher_numero: string;
  medio_pago: string;
  precio_valido_hasta: string;
  precio_descontado: number | null;
};

@Component({
  selector: 'app-separacion-form',
  standalone: true,
  imports: [CommonModule, FormsModule, ClienteBuscadorComponent],
  templateUrl: './separacion-form.component.html',
  styleUrl: './separacion-form.component.css',
})
export class SeparacionFormComponent implements OnInit {
  idProyecto: number | null = null;
  lotesTodos = signal<Lote[]>([]);
  lotesLibres = computed(() => this.lotesTodos().filter((l) => l.estado === 'libre'));

  /** true = el select muestra TODOS los lotes con su estado (carga de datos históricos).
   *  Cuando termine la carga, cámbialo a false y solo saldrán los libres. */
  readonly mostrarTodosLosLotes = true;
  lotesSeleccionables = computed(() => (this.mostrarTodosLosLotes ? this.lotesTodos() : this.lotesLibres()));
  separacionesPorLote = signal<Record<number, { cliente: string; importe: number }>>({});
  manzanas = signal<Manzana[]>([]);
  loteSeleccionado = signal<Lote | null>(null);
  guardando = signal(false);
  error = signal<string | null>(null);
  intentoGuardar = signal(false);

  documentoBusqueda = '';
  buscandoCliente = signal(false);
  clienteEncontrado = signal<Cliente | null>(null);
  clienteNoEncontrado = signal(false);

  form: FormSeparacion = {
    id_lote: null,
    fecha_inicio: this.hoy(),
    fecha_vencimiento: '',
    importe: null,
    motivo: '',
    tipo_pago: null,
    notas: '',
    agenda_fecha: '',
    voucher_numero: '',
    medio_pago: '',
    precio_valido_hasta: '',
    precio_descontado: null,
  };

  /** Proforma rápida de la que viene esta separación (se conserva si hay que registrar al cliente y volver) */
  idProforma: number | null = null;
  private proformaPendiente: Proforma | null = null;
  avisoProforma = signal<string | null>(null);
  private readonly CLAVE_PROFORMA = 'sep_id_proforma';

  subiendoDniFrente = signal(false);
  subiendoDniReverso = signal(false);
  subiendoVoucher = signal(false);
  dniFrenteUrl: string | null = null;
  dniReversoUrl: string | null = null;
  voucherUrl: string | null = null;

  constructor(
    private borrador: BorradorService,
    private api: ApiService,
    private clienteService: ClienteService,
    private separacionService: SeparacionService,
    private proformaService: ProformaService,
    private toastService: ToastService,
    private route: ActivatedRoute,
    private router: Router
  ) {}


  private base = '';
  private salidaLibre = false;

  /** Modal "tienes cambios sin guardar" */
  confirmarSalida = signal(false);

  /** Respuesta pendiente del guard de ruta (solo existe si el modal lo abrió el guard) */
  private resolverGuard: ((puedeSalir: boolean) => void) | null = null;

  /** true mientras se descarta: evita que el autoguardado reviva el borrador */
  private descartando = false;

  private instantanea(): string {
    return JSON.stringify({
      form: this.form,
      cliente: this.clienteEncontrado()?.id ?? null,
      dniFrente: this.dniFrenteUrl,
      dniReverso: this.dniReversoUrl,
      voucher: this.voucherUrl,
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

  private borradorRestaurado = false;

  private get claveBorrador(): string {
    return `separacion-nueva-${this.idProyecto}`;
  }

  guardarBorrador(ahora = false): void {
    if (this.descartando || !this.idProyecto || !this.borradorRestaurado) return;
    const datos = {
      form: this.form,
      idCliente: this.clienteEncontrado()?.id ?? null,
      dniFrenteUrl: this.dniFrenteUrl,
      dniReversoUrl: this.dniReversoUrl,
      voucherUrl: this.voucherUrl,
    };
    if (ahora) this.borrador.guardarYa(this.claveBorrador, datos);
    else this.borrador.guardar(this.claveBorrador, datos);
  }

  private restaurarBorrador(): void {
    if (this.borradorRestaurado) return;
    this.borradorRestaurado = true;
    this.base = this.instantanea();
    const b = this.borrador.leer<{
      form: FormSeparacion;
      idCliente: number | null;
      dniFrenteUrl: string | null;
      dniReversoUrl: string | null;
      voucherUrl: string | null;
    }>(this.claveBorrador);
    if (!b) return;

    this.form = { ...this.form, ...b.form };
    this.loteSeleccionado.set(this.lotesTodos().find((l) => l.id === this.form.id_lote) ?? null);
    this.dniFrenteUrl = b.dniFrenteUrl;
    this.dniReversoUrl = b.dniReversoUrl;
    this.voucherUrl = b.voucherUrl;

    // Si venimos de crear un cliente nuevo, manda ese y no el del borrador
    const vieneClienteNuevo = !!this.route.snapshot.queryParamMap.get('id_cliente');
    if (b.idCliente && !vieneClienteNuevo) {
      this.clienteService.obtener(b.idCliente).subscribe((c) => this.clienteEncontrado.set(c));
    }
    this.toastService.exito('Se recuperó un borrador sin guardar');
  }

  ngOnInit(): void {
    this.route.queryParams.subscribe((params) => {
      const id = Number(params['id_proyecto']);
      this.idProyecto = id || null;
      if (this.idProyecto) this.cargarLotes();

      // Viene de una proforma rápida ("Separar este lote")
      const idPf = Number(params['id_proforma']) || this.leerProformaGuardada();
      if (idPf && idPf !== this.idProforma) {
        this.idProforma = idPf;
        this.guardarProforma(idPf);
        this.cargarProforma(idPf);
      }

      // Volvemos desde "crear cliente nuevo" con el cliente ya creado
      const idCliente = Number(params['id_cliente']);
      if (idCliente) {
        this.clienteService.obtener(idCliente).subscribe((cliente) => {
          this.clienteEncontrado.set(cliente);
          this.clienteNoEncontrado.set(false);
          this.dniFrenteUrl = cliente.dni_frente_url ?? null;
          this.dniReversoUrl = cliente.dni_reverso_url ?? null;
        });
      }
    });
  }

  private hoy(): string {
    return new Date().toISOString().slice(0, 10);
  }

  // ------------------------------------------------ proforma rápida ---

  private leerProformaGuardada(): number | null {
    try {
      return Number(sessionStorage.getItem(this.CLAVE_PROFORMA)) || null;
    } catch {
      return null;
    }
  }

  private guardarProforma(id: number | null): void {
    try {
      if (id) sessionStorage.setItem(this.CLAVE_PROFORMA, String(id));
      else sessionStorage.removeItem(this.CLAVE_PROFORMA);
    } catch {
      /* sin almacenamiento: solo se pierde la recuperación al volver de crear cliente */
    }
  }

  private cargarProforma(id: number): void {
    this.proformaService.obtener(id).subscribe({
      next: (pf) => {
        if (pf.estado === 'convertida') {
          this.toastService.error('Esa proforma ya se usó en otra separación');
          this.idProforma = null;
          this.guardarProforma(null);
          return;
        }
        this.proformaPendiente = pf;
        this.aplicarProforma();
      },
      error: () => {
        this.toastService.error('No se pudo cargar la proforma');
        this.idProforma = null;
        this.guardarProforma(null);
      },
    });
  }

  /** Rellena el formulario con la proforma (cuando ya están cargados los lotes y la proforma) */
  private aplicarProforma(): void {
    const pf = this.proformaPendiente;
    if (!pf || this.lotesTodos().length === 0) return;
    this.proformaPendiente = null;

    const lote = this.lotesSeleccionables().find((l) => l.id === pf.id_lote);
    if (!lote) {
      this.toastService.error(`El lote ${pf.lote_codigo ?? ''} ya no está libre`);
      this.idProforma = null;
      this.guardarProforma(null);
      return;
    }

    this.form.tipo_pago = (pf.tipo_pago as FormaPago | null) ?? null;
    this.form.id_lote = lote.id;
    this.onLoteSeleccionado();
    if (pf.precio_descontado != null) this.form.precio_descontado = Number(pf.precio_descontado);
    if (pf.precio_valido_hasta) this.form.precio_valido_hasta = pf.precio_valido_hasta;
    if (pf.importe != null && Number(pf.importe) > 0) this.form.importe = Number(pf.importe);

    if (pf.id_cliente && !this.clienteEncontrado()) {
      this.clienteService.obtener(pf.id_cliente).subscribe((c) => this.onClienteElegido(c));
    } else if (!pf.id_cliente && !this.clienteEncontrado()) {
      this.avisoProforma.set(
        `Proforma de ${pf.cliente_nombre}: falta registrar al cliente para poder separar. Búscalo o créalo abajo.`
      );
    }
  }

  cargarLotes(): void {
    this.api.get<Lote[]>('/lotes', { id_proyecto: this.idProyecto }).subscribe((res) => {
      this.lotesTodos.set(res);
      this.restaurarBorrador();
      this.aplicarProforma();
    });
    this.api.get<Manzana[]>(`/proyectos/${this.idProyecto}/manzanas`).subscribe((res) => this.manzanas.set(res));

    const activos = ['pendiente_caja', 'pendiente_facturacion', 'vigente', 'vencida', 'devolucion_pendiente'];
    this.separacionService.listar(this.idProyecto!).subscribe((res) => {
      const mapa: Record<number, { cliente: string; importe: number }> = {};
      for (const sep of res) {
        if (activos.includes(sep.estado)) {
          mapa[sep.id_lote] = {
            cliente: sep.cliente ? `${sep.cliente.nombres} ${sep.cliente.apellidos}` : 'Cliente',
            importe: Number(sep.importe),
          };
        }
      }
      this.separacionesPorLote.set(mapa);
    });
  }
  onLoteSeleccionado(): void {
    const lote = this.lotesTodos().find((l) => l.id === this.form.id_lote) ?? null;
    this.loteSeleccionado.set(lote);
    this.aplicarPrecioReferencia();
  }

  /** Precio de lista que corresponde al tipo de pago elegido */
  precioReferencia(): number | null {
    const l = this.loteSeleccionado();
    if (!l) return null;
    const v =
      this.form.tipo_pago === 'contado' ? l.precio_total_contado
      : this.form.tipo_pago === 'credito' ? l.precio_total_financiado
      : l.precio_total_base;
    const n = Number(v);
    return v != null && Number.isFinite(n) && n > 0 ? n : null;
  }

  etiquetaPrecioReferencia(): string {
    if (this.form.tipo_pago === 'contado') return 'Precio contado (lista)';
    if (this.form.tipo_pago === 'credito') return 'Precio financiado (lista)';
    return 'Precio regular';
  }

  aplicarPrecioReferencia(): void {
    this.form.precio_descontado = this.precioReferencia();
  }

  onTipoPagoCambiado(): void {
    this.aplicarPrecioReferencia();
  }

  /** Cuánto se está descontando respecto al precio de lista (negativo = por encima) */
  get descuentoSeparacion(): number | null {
    const ref = this.precioReferencia();
    const p = this.form.precio_descontado;
    if (!ref || !p) return null;
    return ref - p;
  }

  get descuentoSeparacionPct(): number | null {
    const ref = this.precioReferencia();
    const d = this.descuentoSeparacion;
    if (!ref || d === null) return null;
    return (d / ref) * 100;
  }

  /** Etiqueta del campo según lo digitado frente al precio de lista */
  get etiquetaPrecioFinal(): string {
    const d = this.descuentoSeparacion;
    if (d === null || d === 0) return 'Precio final';
    return d > 0 ? 'Precio descontado' : 'Precio aumentado';
  }

  nombreManzana(lote: Lote): string {
    const manzana = this.manzanas().find((m) => m.id === lote.id_manzana);
    return manzana ? manzana.nombre : '—';
  }

  infoOcupacion(lote: Lote): string {
    if (lote.estado === 'libre') return '';
    const info = this.separacionesPorLote()[lote.id];
    if (lote.estado === 'separado' && info) {
      return ` — Separado por ${info.cliente} (S/ ${info.importe.toFixed(2)})`;
    }
    const etiquetas: Record<string, string> = { vendido: 'Vendido', bloqueado: 'Bloqueado', separado: 'Separado' };
    return ` — ${etiquetas[lote.estado] ?? lote.estado}`;
  }

  /** Texto de cada opción del select: código, ubicación y estado del lote */
  etiquetaLote(l: Lote): string {
    const base = `${l.codigo} — ${l.ubicacion_lote || 'sin ubicación'}`;
    return l.estado === 'libre' ? `${base} — Libre` : `${base}${this.infoOcupacion(l)}`;
  }

  buscarCliente(): void {
    const doc = this.documentoBusqueda.trim();
    if (!doc) return;
    this.buscandoCliente.set(true);
    this.clienteEncontrado.set(null);
    this.clienteNoEncontrado.set(false);

    this.clienteService.buscarPorDocumento(doc).subscribe({
      next: (cliente) => {
        this.buscandoCliente.set(false);
        if (cliente) {
          this.clienteEncontrado.set(cliente);
          this.dniFrenteUrl = cliente.dni_frente_url ?? null;
          this.dniReversoUrl = cliente.dni_reverso_url ?? null;
        } else {
          this.clienteNoEncontrado.set(true);
        }
      },
      error: () => {
        this.buscandoCliente.set(false);
        this.toastService.error('No se pudo buscar el cliente');
      },
    });
  }

  onClienteElegido(cliente: Cliente): void {
    this.clienteEncontrado.set(cliente);
    this.clienteNoEncontrado.set(false);
    this.avisoProforma.set(null);
    this.dniFrenteUrl = cliente.dni_frente_url ?? null;
    this.dniReversoUrl = cliente.dni_reverso_url ?? null;
    this.guardarBorrador();
  }

  irACrearClienteNuevo(texto: string): void {
    this.salidaLibre = true;
    this.guardarBorrador(true);
    const esNumero = /^\d{6,}$/.test(texto);
    this.router.navigate(['/dashboard/clientes/nuevo'], {
      queryParams: {
        ...(esNumero ? { documento: texto } : {}),
        returnTo: '/dashboard/separaciones/nueva',
        id_proyecto: this.idProyecto,
      },
    });
  }

  irACrearCliente(): void {
    this.salidaLibre = true;
    this.guardarBorrador(true);
    this.router.navigate(['/dashboard/clientes/nuevo'], {
      queryParams: {
        documento: this.documentoBusqueda.trim(),
        returnTo: '/dashboard/separaciones/nueva',
        id_proyecto: this.idProyecto,
      },
    });
  }

  cambiarCliente(): void {
    this.clienteEncontrado.set(null);
    this.clienteNoEncontrado.set(false);
    this.documentoBusqueda = '';
    this.dniFrenteUrl = null;
    this.dniReversoUrl = null;
    this.guardarBorrador();
  }

  private subirArchivo(archivo: File, destino: 'frente' | 'reverso' | 'voucher'): void {
    const tiposPermitidos = ['image/jpeg', 'image/png', 'application/pdf'];
    if (!tiposPermitidos.includes(archivo.type)) {
      this.toastService.error('Formato no permitido (usa JPG, PNG o PDF)');
      return;
    }
    if (archivo.size > 8 * 1024 * 1024) {
      this.toastService.error('El archivo debe pesar menos de 8MB');
      return;
    }

    const formData = new FormData();
    formData.append('archivo', archivo);

    const flag =
      destino === 'frente' ? this.subiendoDniFrente : destino === 'reverso' ? this.subiendoDniReverso : this.subiendoVoucher;
    flag.set(true);

    this.separacionService.subirArchivo(formData).subscribe({
      next: (res) => {
        flag.set(false);
        if (destino === 'frente') this.dniFrenteUrl = res.url;
        if (destino === 'reverso') this.dniReversoUrl = res.url;
        if (destino === 'voucher') this.voucherUrl = res.url;
        this.guardarBorrador();
      },
      error: (err) => {
        flag.set(false);
        this.toastService.error(err?.error?.detail ?? 'No se pudo subir el archivo');
      },
    });
  }

  onDniFrenteSeleccionado(event: Event): void {
    const input = event.target as HTMLInputElement;
    const archivo = input.files?.[0];
    if (archivo) this.subirArchivo(archivo, 'frente');
    input.value = '';
  }

  onDniReversoSeleccionado(event: Event): void {
    const input = event.target as HTMLInputElement;
    const archivo = input.files?.[0];
    if (archivo) this.subirArchivo(archivo, 'reverso');
    input.value = '';
  }

  onVoucherSeleccionado(event: Event): void {
    const input = event.target as HTMLInputElement;
    const archivo = input.files?.[0];
    if (archivo) this.subirArchivo(archivo, 'voucher');
    input.value = '';
  }

  guardar(): void {
    this.intentoGuardar.set(true);
    const cliente = this.clienteEncontrado();
    if (
      this.mensajeFaltante() ||
      !cliente ||
      !this.form.id_lote ||
      !this.form.importe ||
      !this.form.voucher_numero.trim() ||
      !this.form.medio_pago.trim() ||
      !this.dniFrenteUrl ||
      !this.voucherUrl
    ) {
      return;
    }

    this.error.set(null);
    this.guardando.set(true);

    this.separacionService
      .crear({
        id_lote: this.form.id_lote,
        id_cliente: cliente.id,
        fecha_inicio: this.form.fecha_inicio,
        fecha_vencimiento: this.form.fecha_vencimiento,
        importe: this.form.importe,
        motivo: this.form.motivo || undefined,
        tipo_pago: this.form.tipo_pago || undefined,
        notas: this.form.notas || undefined,
        agenda_fecha: this.form.agenda_fecha ? new Date(this.form.agenda_fecha).toISOString() : undefined,
        dni_frente_url: this.dniFrenteUrl,
        dni_reverso_url: this.dniReversoUrl ?? undefined,
        voucher_url: this.voucherUrl,
        voucher_numero: this.form.voucher_numero.trim(),
        medio_pago: this.form.medio_pago.trim(),
        precio_valido_hasta: this.form.precio_valido_hasta,
        precio_descontado: this.form.precio_descontado ?? undefined,
        id_proforma: this.idProforma ?? undefined,
      })
      .subscribe({
        next: (sep) => {
          this.guardando.set(false);
          this.guardarProforma(null);
          this.borrador.borrar(this.claveBorrador);
          this.salidaLibre = true;
          this.toastService.exito('Separación registrada. Caja debe validar el voucher.');
          this.router.navigate(['/dashboard/separaciones', sep.id]);
        },
        error: (err) => {
          this.guardando.set(false);
          const mensaje = err?.error?.detail ?? 'No se pudo registrar la separación';
          this.error.set(mensaje);
          this.toastService.error(mensaje);
        },
      });
  }

  mensajeFaltante(): string | null {
    if (!this.clienteEncontrado()) return 'Busca o crea el cliente antes de continuar';
    if (!this.form.id_lote) return 'Selecciona el lote';
    if (!this.form.fecha_vencimiento) return 'Indica la fecha de vencimiento de la separación';
    if (!this.form.precio_valido_hasta) return 'Indica hasta qué fecha es válido el precio de la proforma';
    if (this.form.precio_valido_hasta < this.form.fecha_inicio) {
      return 'La validez del precio no puede ser anterior a la fecha inicial';
    }
    if (!this.form.medio_pago.trim()) return 'Indica el medio de pago (ej. Transferencia Yape)';
    if (!this.form.voucher_numero.trim()) return 'Indica el número de voucher';
    if (!this.dniFrenteUrl || !this.voucherUrl) {
      return 'Sube el archivo del DNI (frente y reverso) y el voucher antes de guardar';
    }
    return null;
  }

  cancelar(): void {
    // Con cambios: preguntar qué hacer con el borrador
    if (this.tieneCambiosSinGuardar()) {
      this.confirmarSalida.set(true);
      return;
    }
    // Sin cambios: salir limpio
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
      this.guardarBorrador(true);
    } else {
      this.descartarTodo();
    }
    this.guardarProforma(null);

    this.salidaLibre = true; // para que el guard no vuelva a preguntar
    if (respuestaGuard) respuestaGuard(true); // continúa hacia donde ibas
    else this.irSalida(); // venías del botón Cancelar
  }

  private descartarTodo(): void {
    this.descartando = true;
    this.borrador.borrar(this.claveBorrador);
    this.guardarProforma(null);
  }

  private irSalida(): void {
    this.salidaLibre = true;
    this.router.navigate(['/dashboard/separaciones']);
  }
}