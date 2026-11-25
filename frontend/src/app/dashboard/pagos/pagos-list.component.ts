import { CommonModule } from '@angular/common';
import { Component, OnDestroy, OnInit, computed, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Observable, Subscription } from 'rxjs';

import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { PagoService } from '../../core/services/pago.service';
import { SocketService } from '../../core/services/socket.service';
import { ToastService } from '../../core/services/toast.service';
import { PagoCola, Proyecto } from '../../core/models';
import { comprimirImagen } from '../../core/utils/comprimir-imagen';

type TabPago = 'todos' | 'pendiente_caja' | 'pendiente_facturacion' | 'validado' | 'rechazado' | 'anulado';

@Component({
  selector: 'app-pagos-list',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './pagos-list.component.html',
  styleUrl: './pagos-list.component.css',
})
export class PagosListComponent implements OnInit, OnDestroy {
  proyectos = signal<Proyecto[]>([]);
  idProyecto: number | null = null;
  pagos = signal<PagoCola[]>([]);
  cargando = signal(false);
  procesando = signal(false);
  tab = signal<TabPago>('todos');
  busqueda = signal('');

  pagoRechazo = signal<PagoCola | null>(null);
  motivoRechazo = '';

  pagoComprobante = signal<PagoCola | null>(null);
  comprobanteForm = { tipo: 'boleta', numero: '', archivo_url: '' };
  subiendoArchivo = signal(false);

  
  pagoDevolucion = signal<PagoCola | null>(null);
  devolucionForm = { numero_operacion: '', metodo_pago: 'Transferencia bancaria', voucher_url: '' };
  subiendoVoucherDev = signal(false);

  private sub?: Subscription;

  tabs: { valor: TabPago; etiqueta: string }[] = [
    { valor: 'pendiente_caja', etiqueta: 'Pendientes de Caja' },
    { valor: 'pendiente_facturacion', etiqueta: 'Pendientes de Facturación' },
    { valor: 'validado', etiqueta: 'Aplicados' },
    { valor: 'rechazado', etiqueta: 'Rechazados' },
    { valor: 'anulado', etiqueta: 'Anulados' },
    { valor: 'todos', etiqueta: 'Todos' },
  ];

  conteo = computed(() => {
    const c: Record<string, number> = { todos: this.pagos().length };
    for (const p of this.pagos()) c[p.estado] = (c[p.estado] ?? 0) + 1;
    return c;
  });

  filtrados = computed(() => {
    const tab = this.tab();
    const texto = this.busqueda().trim().toLowerCase();
    return this.pagos().filter((p) => {
      if (tab !== 'todos' && p.estado !== tab) return false;
      if (texto) {
        const base = `${p.numero_contrato} ${p.lote_codigo ?? ''} ${p.cliente_nombre} ${p.cliente_documento} ${p.numero_operacion ?? ''} ${p.concepto ?? ''}`.toLowerCase();
        if (!base.includes(texto)) return false;
      }
      return true;
    });
  });

  constructor(
    private api: ApiService,
    private auth: AuthService,
    private pagoService: PagoService,
    private socket: SocketService,
    private toastService: ToastService
  ) {}

  get rol(): string {
    return this.auth.usuario()?.rol?.clave ?? '';
  }
  get puedeValidar(): boolean {
    return ['admin', 'caja'].includes(this.rol);
  }
  get puedeFacturar(): boolean {
    return ['admin', 'facturacion'].includes(this.rol);
  }

  ngOnInit(): void {
    if (this.rol === 'caja') this.tab.set('pendiente_caja');
    if (this.rol === 'facturacion') this.tab.set('pendiente_facturacion');

    this.api.get<Proyecto[]>('/proyectos').subscribe((proyectos) => {
      this.proyectos.set(proyectos);
      if (proyectos.length > 0) {
        this.idProyecto = proyectos[0].id;
        this.cargar();
      }
    });

    this.socket.conectar();
    this.sub = this.socket.onEvento.subscribe((e) => {
      if (['pago:actualizado', 'contrato:pago_registrado', 'separacion:actualizada', 'socket:conectado'].includes(e.evento)) {
        this.refrescar();
        return;
      }
      const tipo = String((e.data as { tipo?: string })?.tipo ?? '');
      if (
        e.evento === 'notificacion:nueva' &&
        (tipo.startsWith('pago_') || tipo.startsWith('separacion_') || tipo.startsWith('devolucion_'))
      ) {
        this.refrescar();
      }
    });
  }

  private temporizador: ReturnType<typeof setTimeout> | null = null;

  /** Junta ráfagas de eventos (sala proyecto + empresa + notificación) en una sola recarga */
  private refrescar(): void {
    if (this.temporizador) clearTimeout(this.temporizador);
    this.temporizador = setTimeout(() => this.cargar(true), 300);
  }

  ngOnDestroy(): void {
    if (this.temporizador) clearTimeout(this.temporizador);
    this.sub?.unsubscribe();
  }

  cargar(silencioso = false): void {
    if (!this.idProyecto) return;
    if (!silencioso) this.cargando.set(true);
    this.pagoService.listar(this.idProyecto).subscribe({
      next: (res) => {
        this.pagos.set(res);
        this.cargando.set(false);
      },
      error: (err) => {
        this.cargando.set(false);
        console.error('Error al cargar pagos', err);
        this.toastService.error(err?.error?.detail ?? 'No se pudieron cargar los pagos');
      },
    });
  }

  urlCompleta(relativa?: string): string | null {
    if (!relativa) return null;
    if (relativa.startsWith('http://') || relativa.startsWith('https://')) return relativa;
    return this.api.apiUrl + relativa;
  }

  claveFila(p: PagoCola): string {
    return `${p.origen ?? 'pago'}-${p.id}`;
  }

  etiqueta(estado: string): string {
    const mapa: Record<string, string> = {
      pendiente_caja: 'Pendiente de Caja',
      pendiente_facturacion: 'Pendiente de Facturación',
      validado: 'Aplicado',
      rechazado: 'Rechazado',
      anulado: 'Anulado',
    };
    return mapa[estado] ?? estado;
  }

  claseConcepto(p: PagoCola): string {
    if (p.concepto === 'Inicial') return 'concepto-inicial';
    if (p.concepto === 'Pago al contado') return 'concepto-contado';
    return 'concepto-cuota';
  }

  subConcepto(p: PagoCola): string | null {
    if (p.origen === 'devolucion') return 'Se devuelve al cliente: Caja ejecuta y Facturación emite la nota de crédito';
    if (p.origen === 'separacion') return 'Separación de lote: al validarse el lote queda separado';
    if (p.concepto.includes('Cancelación')) return 'Liquida todo el crédito y cierra el contrato';
    if (p.concepto.includes('Amortización')) return 'Abono a capital: reescribe el cronograma';
    if (p.concepto === 'Inicial') return 'Inicial de venta a crédito';
    if (p.concepto === 'Pago al contado') return 'Venta al contado';
    if (p.concepto.startsWith('Cuotas ')) return 'Un solo depósito para varias cuotas';
    return null;
  }

  // ---- Caja ----

  validar(p: PagoCola): void {
    this.procesando.set(true);
    const llamada: Observable<unknown> =
      p.origen === 'separacion'
        ? this.api.post<unknown>(`/separaciones/${p.id}/validar`, {})
        : this.pagoService.validar(p.id);
    llamada.subscribe({
      next: () => {
        this.procesando.set(false);
        this.toastService.exito(`${p.concepto} validado. Pasó a Facturación.`);
        this.cargar(true);
      },
      error: (err) => {
        this.procesando.set(false);
        this.toastService.error(err?.error?.detail ?? 'No se pudo validar');
      },
    });
  }

  abrirRechazo(p: PagoCola): void {
    this.motivoRechazo = '';
    this.pagoRechazo.set(p);
  }

  confirmarRechazo(): void {
    const p = this.pagoRechazo();
    if (!p) return;
    const motivo = this.motivoRechazo.trim();
    if (!motivo) {
      this.toastService.error('Indica el motivo del rechazo');
      return;
    }
    this.procesando.set(true);
    // Según dónde esté el pago: Caja o Facturación
    const llamada: Observable<unknown> =
      p.origen === 'separacion'
        ? this.api.post<unknown>(
            `/separaciones/${p.id}/${p.estado === 'pendiente_facturacion' ? 'rechazar-facturacion' : 'rechazar'}`,
            { motivo }
          )
        : p.estado === 'pendiente_facturacion'
          ? this.pagoService.rechazarFacturacion(p.id, motivo)
          : this.pagoService.rechazar(p.id, motivo);
    llamada.subscribe({
      next: () => {
        this.procesando.set(false);
        this.pagoRechazo.set(null);
        this.toastService.exito('Pago rechazado. Se avisó al área de ventas para que lo corrija.');
        this.cargar(true);
      },
      error: (err) => {
        this.procesando.set(false);
        this.toastService.error(err?.error?.detail ?? 'No se pudo rechazar el pago');
      },
    });
  }



    // ---- Devolución de separación (Caja) ----

  abrirDevolucion(p: PagoCola): void {
    this.devolucionForm = { numero_operacion: '', metodo_pago: 'Transferencia bancaria', voucher_url: '' };
    this.pagoDevolucion.set(p);
  }

  async onArchivoDevolucion(event: Event): Promise<void> {
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
    this.subiendoVoucherDev.set(true);
    const formData = new FormData();
    formData.append('archivo', await comprimirImagen(archivo));
    this.pagoService.subirArchivo(formData).subscribe({
      next: (res) => {
        this.devolucionForm.voucher_url = res.url;
        this.subiendoVoucherDev.set(false);
      },
      error: (err) => {
        this.subiendoVoucherDev.set(false);
        this.toastService.error(err?.error?.detail ?? 'No se pudo subir el voucher');
      },
    });
  }

  confirmarDevolucion(): void {
    const p = this.pagoDevolucion();
    if (!p) return;
    if (!this.devolucionForm.numero_operacion.trim() || !this.devolucionForm.voucher_url) {
      this.toastService.error('Indica el N° de operación y sube el voucher de la devolución');
      return;
    }
    this.procesando.set(true);
    this.api.post<unknown>(`/separaciones/devoluciones/${p.id}/ejecutar`, this.devolucionForm).subscribe({
      next: () => {
        this.procesando.set(false);
        this.pagoDevolucion.set(null);
        this.toastService.exito('Devolución registrada. Pasó a Facturación para la nota de crédito.');
        this.cargar(true);
      },
      error: (err) => {
        this.procesando.set(false);
        this.toastService.error(err?.error?.detail ?? 'No se pudo registrar la devolución');
      },
    });
  }


  // ---- Facturación ----

  abrirComprobante(p: PagoCola): void {
    this.comprobanteForm = { tipo: 'boleta', numero: '', archivo_url: '' };
    this.pagoComprobante.set(p);
  }

  async onArchivoComprobante(event: Event): Promise<void> {
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
    this.subiendoArchivo.set(true);
    const formData = new FormData();
    formData.append('archivo', await comprimirImagen(archivo));
    this.pagoService.subirArchivo(formData).subscribe({
      next: (res) => {
        this.comprobanteForm.archivo_url = res.url;
        this.subiendoArchivo.set(false);
      },
      error: (err) => {
        this.subiendoArchivo.set(false);
        this.toastService.error(err?.error?.detail ?? 'No se pudo subir el archivo');
      },
    });
  }

  confirmarComprobante(): void {
    const p = this.pagoComprobante();
    if (!p) return;
    if (!this.comprobanteForm.numero.trim() || !this.comprobanteForm.archivo_url) {
      this.toastService.error('Indica el número y sube el archivo del comprobante');
      return;
    }
    this.procesando.set(true);
    const llamada: Observable<unknown> =
      p.origen === 'devolucion'
        ? this.api.post<unknown>(`/separaciones/devoluciones/${p.id}/nota-credito`, {
            numero: this.comprobanteForm.numero.trim(),
            archivo_url: this.comprobanteForm.archivo_url,
          })
        : p.origen === 'separacion'
          ? this.api.post<unknown>(`/separaciones/${p.id}/comprobante`, this.comprobanteForm)
          : this.pagoService.subirComprobante(p.id, this.comprobanteForm);
    llamada.subscribe({
      next: () => {
        this.procesando.set(false);
        this.pagoComprobante.set(null);
                if (p.origen === 'devolucion') {
          this.toastService.exito('Nota de crédito registrada. Devolución completada.');
          this.cargar(true);
          return;
        }
        if (p.origen === 'separacion') {
          this.toastService.exito('Comprobante registrado. La separación está vigente.');
          this.cargar(true);
          return;
        }
        this.toastService.exito(
          p.concepto.includes('Cancelación')
            ? 'Comprobante registrado. El crédito quedó cancelado.'
            : p.concepto.includes('Amortización')
              ? 'Comprobante registrado. El cronograma se actualizó con la amortización.'
              : p.concepto === 'Inicial' || p.concepto === 'Pago al contado'
                ? 'Comprobante registrado. El pago quedó aplicado al contrato.'
                : 'Comprobante registrado. El pago ya se aplicó a la cuota.'
        );
        this.cargar(true);
      },
      error: (err) => {
        this.procesando.set(false);
        this.toastService.error(err?.error?.detail ?? 'No se pudo registrar el comprobante');
      },
    });
  }
}