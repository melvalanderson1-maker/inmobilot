import { CommonModule } from '@angular/common';
import { Component, OnDestroy, OnInit, computed, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Subscription } from 'rxjs';

import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { PagoService } from '../../core/services/pago.service';
import { SocketService } from '../../core/services/socket.service';
import { ToastService } from '../../core/services/toast.service';
import { PagoCola, Proyecto } from '../../core/models';

type TabPago = 'todos' | 'pendiente_caja' | 'pendiente_facturacion' | 'validado' | 'rechazado';

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

  private sub?: Subscription;

  tabs: { valor: TabPago; etiqueta: string }[] = [
    { valor: 'pendiente_caja', etiqueta: 'Pendientes de Caja' },
    { valor: 'pendiente_facturacion', etiqueta: 'Pendientes de Facturación' },
    { valor: 'validado', etiqueta: 'Aplicados' },
    { valor: 'rechazado', etiqueta: 'Rechazados' },
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
        const base = `${p.numero_contrato} ${p.lote_codigo ?? ''} ${p.cliente_nombre} ${p.cliente_documento} ${p.numero_operacion ?? ''}`.toLowerCase();
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
      if (e.evento === 'pago:actualizado' || e.evento === 'contrato:pago_registrado') this.cargar(true);
    });
  }

  ngOnDestroy(): void {
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
      error: () => this.cargando.set(false),
    });
  }

  urlCompleta(relativa?: string): string | null {
    if (!relativa) return null;
    if (relativa.startsWith('http://') || relativa.startsWith('https://')) return relativa;
    return this.api.apiUrl + relativa;
  }

  etiqueta(estado: string): string {
    const mapa: Record<string, string> = {
      pendiente_caja: 'Pendiente de Caja',
      pendiente_facturacion: 'Pendiente de Facturación',
      validado: 'Aplicado',
      rechazado: 'Rechazado',
    };
    return mapa[estado] ?? estado;
  }

  // ---- Caja ----

  validar(p: PagoCola): void {
    this.procesando.set(true);
    this.pagoService.validar(p.id).subscribe({
      next: () => {
        this.procesando.set(false);
        this.toastService.exito('Pago validado. Pasó a Facturación.');
        this.cargar(true);
      },
      error: (err) => {
        this.procesando.set(false);
        this.toastService.error(err?.error?.detail ?? 'No se pudo validar el pago');
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
    if (!this.motivoRechazo.trim()) {
      this.toastService.error('Indica el motivo del rechazo');
      return;
    }
    this.procesando.set(true);
    this.pagoService.rechazar(p.id, this.motivoRechazo.trim()).subscribe({
      next: () => {
        this.procesando.set(false);
        this.pagoRechazo.set(null);
        this.toastService.exito('Pago rechazado');
        this.cargar(true);
      },
      error: (err) => {
        this.procesando.set(false);
        this.toastService.error(err?.error?.detail ?? 'No se pudo rechazar el pago');
      },
    });
  }

  // ---- Facturación ----

  abrirComprobante(p: PagoCola): void {
    this.comprobanteForm = { tipo: 'boleta', numero: '', archivo_url: '' };
    this.pagoComprobante.set(p);
  }

  onArchivoComprobante(event: Event): void {
    const input = event.target as HTMLInputElement;
    const archivo = input.files?.[0];
    if (!archivo) return;
    const formData = new FormData();
    formData.append('archivo', archivo);
    this.subiendoArchivo.set(true);
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
    input.value = '';
  }

  confirmarComprobante(): void {
    const p = this.pagoComprobante();
    if (!p) return;
    if (!this.comprobanteForm.numero.trim() || !this.comprobanteForm.archivo_url) {
      this.toastService.error('Indica el número y sube el archivo del comprobante');
      return;
    }
    this.procesando.set(true);
    this.pagoService.subirComprobante(p.id, this.comprobanteForm).subscribe({
      next: () => {
        this.procesando.set(false);
        this.pagoComprobante.set(null);
        this.toastService.exito('Comprobante registrado. El pago ya se aplicó a la cuota.');
        this.cargar(true);
      },
      error: (err) => {
        this.procesando.set(false);
        this.toastService.error(err?.error?.detail ?? 'No se pudo registrar el comprobante');
      },
    });
  }
}