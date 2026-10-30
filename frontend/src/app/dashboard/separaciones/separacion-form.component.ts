import { CommonModule } from '@angular/common';
import { Component, OnInit, computed, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';

import { ApiService } from '../../core/services/api.service';
import { ClienteService } from '../../core/services/cliente.service';
import { ProformaService } from '../../core/services/proforma.service';
import { SeparacionService } from '../../core/services/separacion.service';
import { ToastService } from '../../core/services/toast.service';
import { Cliente, FormaPago, Lote, Manzana, Proforma } from '../../core/models';
import { ClienteBuscadorComponent } from '../../shared/cliente-buscador/cliente-buscador.component';

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

  form = {
    id_lote: null as number | null,
    fecha_inicio: this.hoy(),
    fecha_vencimiento: '',
    importe: null as number | null,
    motivo: '',
    tipo_pago: null as FormaPago | null,
    notas: '',
    agenda_fecha: '',
    voucher_numero: '',
    medio_pago: '',
    precio_valido_hasta: '',
    precio_descontado: null as number | null,
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
    private api: ApiService,
    private clienteService: ClienteService,
    private separacionService: SeparacionService,
    private proformaService: ProformaService,
    private toastService: ToastService,
    private route: ActivatedRoute,
    private router: Router
  ) {}

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

    const lote = this.lotesLibres().find((l) => l.id === pf.id_lote);
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
  }

  irACrearClienteNuevo(texto: string): void {
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
    const referencia = this.precioReferencia();
    if (this.form.precio_descontado && referencia && this.form.precio_descontado > referencia) {
      return `El precio final no puede superar el ${this.etiquetaPrecioReferencia().toLowerCase()}`;
    }
    if (!this.form.medio_pago.trim()) return 'Indica el medio de pago (ej. Transferencia Yape)';
    if (!this.form.voucher_numero.trim()) return 'Indica el número de voucher';
    if (!this.dniFrenteUrl || !this.voucherUrl) {
      return 'Sube el archivo del DNI (frente y reverso) y el voucher antes de guardar';
    }
    return null;
  }

  cancelar(): void {
    this.guardarProforma(null);
    this.router.navigate(['/dashboard/separaciones']);
  }
}