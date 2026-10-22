import { CommonModule } from '@angular/common';
import { Component, OnDestroy, OnInit, computed, signal } from '@angular/core';
import { DomSanitizer, SafeResourceUrl } from '@angular/platform-browser';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { Subscription } from 'rxjs';

import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { SocketService } from '../../core/services/socket.service';
import { SeparacionService } from '../../core/services/separacion.service';
import { ToastService } from '../../core/services/toast.service';
import { FormaPago, Separacion } from '../../core/models';
import { AutorizacionVentaComponent } from '../../shared/autorizacion-venta/autorizacion-venta.component';


type TabDocClave = 'proforma' | 'contrato' | 'contrato_firmado' | 'dni_frente' | 'dni_reverso' | 'voucher';

interface DocTab {
  clave: TabDocClave;
  etiqueta: string;
  url: string | null;
}

@Component({
  selector: 'app-separacion-detalle',
  standalone: true,
  imports: [CommonModule, FormsModule, AutorizacionVentaComponent],
  templateUrl: './separacion-detalle.component.html',
  styleUrl: './separacion-detalle.component.css',
})
export class SeparacionDetalleComponent implements OnInit, OnDestroy {
  separacion = signal<Separacion | null>(null);
  cargando = signal(false);
  procesando = signal(false);
  idSeparacion!: number;
  idVenta = signal<number | null>(null);

  mostrarRechazo = signal(false);
  motivoRechazo = '';

  mostrarComprobante = signal(false);
  comprobanteForm = { tipo: 'boleta', numero: '', archivo_url: '' };
  subiendoArchivoComprobante = signal(false);

  mostrarDevolucion = signal(false);
  devolucionForm = { monto: null as number | null, sustento: '', continua_venta: false };

  mostrarResolverDevolucion = signal(false);
  respuestaDevolucion = '';

  mostrarEditar = signal(false);
  editarForm = {
    fecha_vencimiento: '',
    tipo_pago: null as FormaPago | null,
    notas: '',
    agenda_fecha: '',
    precio_valido_hasta: '',
    precio_descontado: null as number | null,
  };


  subiendoContratoFirmado = signal(false);
  generandoProforma = signal(false);
  private sub?: Subscription;



    tabActiva = signal<TabDocClave>('proforma');

  documentos = computed<DocTab[]>(() => {
    const s = this.separacion();
    const docs: DocTab[] = [
      { clave: 'proforma',         etiqueta: 'Proforma',          url: s?.proforma_url ?? null },
      { clave: 'contrato',         etiqueta: 'Contrato',          url: s?.contrato_url ?? null },
      { clave: 'contrato_firmado', etiqueta: 'Contrato firmado',  url: s?.contrato_firmado_url ?? null },
      { clave: 'dni_frente',       etiqueta: 'DNI',               url: s?.dni_frente_url ?? null },
      { clave: 'dni_reverso',      etiqueta: 'DNI reverso',       url: s?.dni_reverso_url ?? null },
      { clave: 'voucher',          etiqueta: 'Voucher',           url: s?.voucher_url ?? null },
    ];
    // El reverso solo aparece en separaciones antiguas que ya lo tienen subido
    return docs.filter((d) => d.clave !== 'dni_reverso' || !!d.url);
  });

  docsDisponibles = computed(() => this.documentos().filter((d) => !!d.url).length);

  docActivo = computed(() => this.documentos().find((d) => d.clave === this.tabActiva())!);

  esImagen = computed(() => /\.(jpe?g|png|webp|gif)(\?.*)?$/i.test(this.docActivo().url ?? ''));

  nombreDoc = computed(() => {
    const url = this.docActivo().url;
    if (!url) return 'Sin archivo';
    try {
      return decodeURIComponent(url.split('?')[0].split('/').pop() || 'documento');
    } catch {
      return 'documento';
    }
  });

  urlSegura = computed<SafeResourceUrl | null>(() => {
    const url = this.docActivo().url;
    return url ? this.sanitizer.bypassSecurityTrustResourceUrl(url) : null;
  });

  constructor(
    private api: ApiService,
    private auth: AuthService,
    private socket: SocketService,
    private separacionService: SeparacionService,
    private toastService: ToastService,
    private route: ActivatedRoute,
    private router: Router,
    private sanitizer: DomSanitizer
  ) {}

  ngOnInit(): void {
    this.idSeparacion = Number(this.route.snapshot.paramMap.get('id'));
    this.cargar();

    this.socket.conectar();
    this.sub = this.socket.onEvento.subscribe((evento) => {
      if (evento.evento === 'separacion:actualizada') {
        const data = evento.data as { id?: number };
        if (data?.id === this.idSeparacion) this.cargar(true);
      }
      // Respaldo: la notificación privada llega aunque no estés en la sala del proyecto
      if (evento.evento === 'notificacion:nueva') {
        const n = evento.data as { data?: { id_separacion?: number } };
        if (Number(n?.data?.id_separacion) === this.idSeparacion) this.cargar(true);
      }
    });
  }

  ngOnDestroy(): void {
    this.sub?.unsubscribe();
    this.socket.desconectar();
  }

  get rolClave(): string {
    return this.auth.usuario()?.rol?.clave ?? '';
  }

  cargar(silencioso = false): void {
    if (!silencioso) this.cargando.set(true);
    this.separacionService.obtener(this.idSeparacion).subscribe({
      next: (res) => {
        this.separacion.set(res);
        this.idVenta.set(null);
        if (res.estado === 'convertida') {
          this.api.get<{ id_venta: number | null }>('/ventas/por-separacion/' + res.id).subscribe({
            next: (r) => this.idVenta.set(r.id_venta),
            error: () => this.idVenta.set(null),
          });
        }
        this.cargando.set(false);
      },
      error: () => this.cargando.set(false),
    });
  }

  puedeIniciarVenta(): boolean {
    const sep = this.separacion();
    return !!sep && sep.estado === 'convertida' && !this.idVenta();
  }

  iniciarVenta(): void {
    this.router.navigate(['/dashboard/separaciones', this.idSeparacion, 'iniciar-venta']);
  }

  verVenta(): void {
    this.router.navigate(['/dashboard/ventas', this.idVenta()]);
  }

  volver(): void {
    this.router.navigate(['/dashboard/separaciones']);
  }

  puedeValidar(): boolean {
    const sep = this.separacion();
    return !!sep && sep.estado === 'pendiente_caja' && ['admin', 'caja'].includes(this.rolClave);
  }

  validar(): void {
    this.procesando.set(true);
    this.separacionService.validar(this.idSeparacion).subscribe({
      next: () => {
        this.procesando.set(false);
        this.toastService.exito('Voucher validado. El lote pasó a separado.');
        this.cargar();
      },
      error: (err) => {
        this.procesando.set(false);
        this.toastService.error(err?.error?.detail ?? 'No se pudo validar el voucher');
      },
    });
  }

  abrirRechazo(): void {
    this.motivoRechazo = '';
    this.mostrarRechazo.set(true);
  }

  confirmarRechazo(): void {
    if (!this.motivoRechazo.trim()) {
      this.toastService.error('Indica el motivo del rechazo');
      return;
    }
    this.procesando.set(true);
    this.separacionService.rechazar(this.idSeparacion, this.motivoRechazo.trim()).subscribe({
      next: () => {
        this.procesando.set(false);
        this.mostrarRechazo.set(false);
        this.toastService.exito('Separación rechazada');
        this.cargar();
      },
      error: (err) => {
        this.procesando.set(false);
        this.toastService.error(err?.error?.detail ?? 'No se pudo rechazar');
      },
    });
  }

  puedeSubirComprobante(): boolean {
    const sep = this.separacion();
    return !!sep && sep.estado === 'pendiente_facturacion' && ['admin', 'facturacion'].includes(this.rolClave);
  }

  abrirComprobante(): void {
    this.comprobanteForm = { tipo: 'boleta', numero: '', archivo_url: '' };
    this.mostrarComprobante.set(true);
  }

  onArchivoComprobante(event: Event): void {
    const input = event.target as HTMLInputElement;
    const archivo = input.files?.[0];
    if (!archivo) return;

    const formData = new FormData();
    formData.append('archivo', archivo);
    this.subiendoArchivoComprobante.set(true);

    this.separacionService.subirArchivo(formData).subscribe({
      next: (res) => {
        this.comprobanteForm.archivo_url = res.url;
        this.subiendoArchivoComprobante.set(false);
      },
      error: (err) => {
        this.subiendoArchivoComprobante.set(false);
        this.toastService.error(err?.error?.detail ?? 'No se pudo subir el archivo');
      },
    });
    input.value = '';
  }

  confirmarComprobante(): void {
    if (!this.comprobanteForm.numero.trim() || !this.comprobanteForm.archivo_url) {
      this.toastService.error('Indica el número y sube el archivo del comprobante');
      return;
    }
    this.procesando.set(true);
    this.separacionService.subirComprobante(this.idSeparacion, this.comprobanteForm).subscribe({
      next: () => {
        this.procesando.set(false);
        this.mostrarComprobante.set(false);
        this.toastService.exito('Comprobante registrado. La separación está vigente.');
        this.cargar();
      },
      error: (err) => {
        this.procesando.set(false);
        this.toastService.error(err?.error?.detail ?? 'No se pudo registrar el comprobante');
      },
    });
  }

  puedeConvertir(): boolean {
    const sep = this.separacion();
    return !!sep && sep.estado === 'vigente';
  }

  convertir(): void {
    this.procesando.set(true);
    this.separacionService.convertir(this.idSeparacion).subscribe({
      next: () => {
        this.procesando.set(false);
        this.toastService.exito('Separación marcada como convertida a venta');
        this.router.navigate(['/dashboard/separaciones', this.idSeparacion, 'iniciar-venta']);
      },
      error: (err) => {
        this.procesando.set(false);
        this.toastService.error(err?.error?.detail ?? 'No se pudo convertir');
      },
    });
  }

  puedeSolicitarDevolucion(): boolean {
    const sep = this.separacion();
    if (!sep || !['vigente', 'vencida', 'convertida'].includes(sep.estado)) return false;
    const devuelto = (sep.devoluciones ?? [])
      .filter((d) => d.estado === 'aprobada')
      .reduce((a, d) => a + Number(d.monto), 0);
    const pendiente = (sep.devoluciones ?? []).some((d) => d.estado === 'pendiente');
    return !pendiente && devuelto < Number(sep.importe);
  }

  abrirDevolucion(): void {
    const sep = this.separacion();
    this.devolucionForm = {
      monto: sep ? Number(sep.importe) : null,
      sustento: '',
      continua_venta: sep?.estado === 'convertida',
    };
    this.mostrarDevolucion.set(true);
  }

  confirmarDevolucion(): void {
    if (!this.devolucionForm.monto || this.devolucionForm.monto <= 0 || !this.devolucionForm.sustento.trim()) {
      this.toastService.error('Indica el monto y el sustento de la devolución');
      return;
    }
    this.procesando.set(true);
    this.separacionService
      .solicitarDevolucion(this.idSeparacion, {
        monto: this.devolucionForm.monto,
        sustento: this.devolucionForm.sustento.trim(),
        continua_venta: this.devolucionForm.continua_venta,
      })
      .subscribe({
        next: () => {
          this.procesando.set(false);
          this.mostrarDevolucion.set(false);
          this.toastService.exito('Devolución solicitada. Gerencia debe aprobarla.');
          this.cargar();
        },
        error: (err) => {
          this.procesando.set(false);
          this.toastService.error(err?.error?.detail ?? 'No se pudo solicitar la devolución');
        },
      });
  }

  puedeResolverDevolucion(): boolean {
    const sep = this.separacion();
    return !!sep && sep.devoluciones.some((d) => d.estado === 'pendiente') && ['admin', 'gerencia'].includes(this.rolClave);
  }

  abrirResolverDevolucion(): void {
    this.respuestaDevolucion = '';
    this.mostrarResolverDevolucion.set(true);
  }

  resolverDevolucion(aprobar: boolean): void {
    this.procesando.set(true);
    this.separacionService
      .resolverDevolucion(this.idSeparacion, { aprobar, respuesta: this.respuestaDevolucion || undefined })
      .subscribe({
        next: () => {
          this.procesando.set(false);
          this.mostrarResolverDevolucion.set(false);
          this.toastService.exito(aprobar ? 'Devolución aprobada.' : 'Devolución rechazada.');
          this.cargar();
        },
        error: (err) => {
          this.procesando.set(false);
          this.toastService.error(err?.error?.detail ?? 'No se pudo resolver la devolución');
        },
      });
  }

  puedeLiberar(): boolean {
    const sep = this.separacion();
    if (!sep || !['admin', 'gerencia', 'supervisor'].includes(this.rolClave)) return false;
    const devuelto = (sep.devoluciones ?? [])
      .filter((d) => d.estado === 'aprobada')
      .reduce((a, d) => a + Number(d.monto), 0);
    return sep.estado === 'vencida' || (sep.estado === 'vigente' && devuelto >= Number(sep.importe));
  }

  liberar(): void {
    this.procesando.set(true);
    this.separacionService.liberar(this.idSeparacion).subscribe({
      next: () => {
        this.procesando.set(false);
        this.toastService.exito('Lote liberado');
        this.cargar();
      },
      error: (err) => {
        this.procesando.set(false);
        this.toastService.error(err?.error?.detail ?? 'No se pudo liberar el lote');
      },
    });
  }

  puedeEditar(): boolean {
    const sep = this.separacion();
    return !!sep && !['convertida', 'devuelta', 'rechazada'].includes(sep.estado);
  }

  abrirEditar(): void {
    const sep = this.separacion();
    if (!sep) return;
    this.editarForm = {
      fecha_vencimiento: sep.fecha_vencimiento,
      tipo_pago: sep.tipo_pago ?? null,
      notas: sep.notas ?? '',
      agenda_fecha: sep.agenda_fecha ? sep.agenda_fecha.slice(0, 16) : '',
      precio_valido_hasta: sep.precio_valido_hasta ?? '',
      precio_descontado: sep.precio_descontado != null ? Number(sep.precio_descontado) : null,
    };
    this.mostrarEditar.set(true);
  }

  guardarEdicion(): void {
    this.procesando.set(true);
    this.separacionService
      .actualizar(this.idSeparacion, {
        fecha_vencimiento: this.editarForm.fecha_vencimiento || undefined,
        tipo_pago: this.editarForm.tipo_pago || undefined,
        notas: this.editarForm.notas || undefined,
        agenda_fecha: this.editarForm.agenda_fecha ? new Date(this.editarForm.agenda_fecha).toISOString() : undefined,
        precio_valido_hasta: this.editarForm.precio_valido_hasta || undefined,
        precio_descontado: this.editarForm.precio_descontado || undefined,
      })
      .subscribe({
        next: () => {
          this.procesando.set(false);
          this.mostrarEditar.set(false);
          this.toastService.exito('Separación actualizada');
          this.cargar();
        },
        error: (err) => {
          this.procesando.set(false);
          this.toastService.error(err?.error?.detail ?? 'No se pudo actualizar');
        },
      });
  }

  generandoContrato = signal(false);

  generarContrato(): void {
    this.generandoContrato.set(true);
    this.separacionService.generarContrato(this.idSeparacion).subscribe({
      next: () => {
        this.generandoContrato.set(false);
        this.toastService.exito('Contrato generado');
        this.tabActiva.set('contrato');
        this.cargar();
      },
      error: (err) => {
        this.generandoContrato.set(false);
        this.toastService.error(err?.error?.detail ?? 'No se pudo generar el contrato');
      },
    });
  }

  onContratoFirmadoSeleccionado(event: Event): void {
    const input = event.target as HTMLInputElement;
    const archivo = input.files?.[0];
    if (!archivo) return;
    const formData = new FormData();
    formData.append('archivo', archivo);
    this.subiendoContratoFirmado.set(true);
    this.separacionService.subirArchivo(formData).subscribe({
      next: (res) => {
        this.separacionService.actualizar(this.idSeparacion, { contrato_firmado_url: res.url }).subscribe({
          next: () => {
            this.subiendoContratoFirmado.set(false);
            this.toastService.exito('Contrato firmado subido. Ya puedes convertir la separación en venta.');
            this.cargar();
          },
          error: (err) => {
            this.subiendoContratoFirmado.set(false);
            this.toastService.error(err?.error?.detail ?? 'No se pudo guardar el contrato firmado');
          },
        });
      },
      error: (err) => {
        this.subiendoContratoFirmado.set(false);
        this.toastService.error(err?.error?.detail ?? 'No se pudo subir el archivo');
      },
    });
    input.value = '';
  }

  generarProforma(): void {
    this.generandoProforma.set(true);
    this.separacionService.generarProforma(this.idSeparacion).subscribe({
      next: () => {
        this.generandoProforma.set(false);
        this.toastService.exito('Proforma generada');
        this.cargar();
      },
      error: (err) => {
        this.generandoProforma.set(false);
        this.toastService.error(err?.error?.detail ?? 'No se pudo generar la proforma');
      },
    });
  }

  etiquetaEstado(estado: string): string {
    const mapa: Record<string, string> = {
      pendiente_caja: 'Pendiente validación de Caja',
      pendiente_facturacion: 'Pendiente comprobante de Facturación',
      vigente: 'Vigente',
      vencida: 'Vencida',
      convertida: 'Convertida a venta',
      devolucion_pendiente: 'Devolución pendiente de aprobación',
      devuelta: 'Devuelta',
      rechazada: 'Rechazada',
    };
    return mapa[estado] ?? estado;
  }



   mensajeVacio(clave: TabDocClave): string {
    const mapa: Record<TabDocClave, string> = {
      proforma: 'La proforma aún no se ha generado. Usa el botón "Generar".',
      contrato: 'El contrato aún no se ha generado. Usa el botón "Generar".',
      contrato_firmado: 'El contrato firmado aún no se ha subido.',
      dni_frente: 'No hay archivo del DNI.',
      dni_reverso: 'No hay foto del DNI (reverso).',
      voucher: 'No hay voucher adjunto.',
    };
    return mapa[clave];
  }
}