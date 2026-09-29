import { CommonModule } from '@angular/common';
import { Component, OnDestroy, OnInit, computed, signal } from '@angular/core';
import { DomSanitizer, SafeResourceUrl } from '@angular/platform-browser';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';

import { AuthService } from '../../core/services/auth.service';
import { SocketService } from '../../core/services/socket.service';
import { SeparacionService } from '../../core/services/separacion.service';
import { ToastService } from '../../core/services/toast.service';
import { FormaPago, Separacion } from '../../core/models';


type TabDocClave = 'proforma' | 'contrato' | 'contrato_firmado' | 'dni_frente' | 'dni_reverso' | 'voucher';

interface DocTab {
  clave: TabDocClave;
  etiqueta: string;
  url: string | null;
}

@Component({
  selector: 'app-separacion-detalle',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './separacion-detalle.component.html',
  styleUrl: './separacion-detalle.component.css',
})
export class SeparacionDetalleComponent implements OnInit, OnDestroy {
  separacion = signal<Separacion | null>(null);
  cargando = signal(false);
  procesando = signal(false);
  idSeparacion!: number;

  mostrarRechazo = signal(false);
  motivoRechazo = '';

  mostrarComprobante = signal(false);
  comprobanteForm = { tipo: 'boleta', numero: '', archivo_url: '' };
  subiendoArchivoComprobante = signal(false);

  mostrarDevolucion = signal(false);
  devolucionForm = { monto: null as number | null, sustento: '' };

  mostrarResolverDevolucion = signal(false);
  respuestaDevolucion = '';

  mostrarEditar = signal(false);
  editarForm = { fecha_vencimiento: '', tipo_pago: null as FormaPago | null, notas: '', agenda_fecha: '' };

  subiendoContrato = signal(false);
  subiendoContratoFirmado = signal(false);
  generandoProforma = signal(false);



    tabActiva = signal<TabDocClave>('proforma');

  documentos = computed<DocTab[]>(() => {
    const s = this.separacion();
    return [
      { clave: 'proforma',         etiqueta: 'Proforma',          url: s?.proforma_url ?? null },
      { clave: 'contrato',         etiqueta: 'Contrato',          url: s?.contrato_url ?? null },
      { clave: 'contrato_firmado', etiqueta: 'Contrato firmado',  url: s?.contrato_firmado_url ?? null },
      { clave: 'dni_frente',       etiqueta: 'DNI frente',        url: s?.dni_frente_url ?? null },
      { clave: 'dni_reverso',      etiqueta: 'DNI reverso',       url: s?.dni_reverso_url ?? null },
      { clave: 'voucher',          etiqueta: 'Voucher',           url: s?.voucher_url ?? null },
    ];
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
    this.socket.onEvento.subscribe((evento) => {
      if (evento.evento === 'separacion:actualizada') {
        const data = evento.data as { id?: number };
        if (data?.id === this.idSeparacion) this.cargar();
      }
    });
  }

  ngOnDestroy(): void {
    this.socket.desconectar();
  }

  get rolClave(): string {
    return this.auth.usuario()?.rol?.clave ?? '';
  }

  cargar(): void {
    this.cargando.set(true);
    this.separacionService.obtener(this.idSeparacion).subscribe({
      next: (res) => {
        this.separacion.set(res);
        this.cargando.set(false);
      },
      error: () => this.cargando.set(false),
    });
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
        this.cargar();
      },
      error: (err) => {
        this.procesando.set(false);
        this.toastService.error(err?.error?.detail ?? 'No se pudo convertir');
      },
    });
  }

  puedeSolicitarDevolucion(): boolean {
    const sep = this.separacion();
    return !!sep && ['vigente', 'vencida'].includes(sep.estado);
  }

  abrirDevolucion(): void {
    const sep = this.separacion();
    this.devolucionForm = { monto: sep ? Number(sep.importe) : null, sustento: '' };
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
    return !!sep && sep.estado === 'devolucion_pendiente' && ['admin', 'gerencia'].includes(this.rolClave);
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
          this.toastService.exito(aprobar ? 'Devolución aprobada. Lote liberado.' : 'Devolución rechazada.');
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
    return !!sep && sep.estado === 'vencida' && ['admin', 'gerencia', 'supervisor'].includes(this.rolClave);
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

  onContratoSeleccionado(event: Event): void {
    const input = event.target as HTMLInputElement;
    const archivo = input.files?.[0];
    if (!archivo) return;
    const formData = new FormData();
    formData.append('archivo', archivo);
    this.subiendoContrato.set(true);
    this.separacionService.subirArchivo(formData).subscribe({
      next: (res) => {
        this.separacionService.actualizar(this.idSeparacion, { contrato_url: res.url }).subscribe({
          next: () => {
            this.subiendoContrato.set(false);
            this.toastService.exito('Contrato de separación subido');
            this.cargar();
          },
          error: (err) => {
            this.subiendoContrato.set(false);
            this.toastService.error(err?.error?.detail ?? 'No se pudo guardar el contrato');
          },
        });
      },
      error: (err) => {
        this.subiendoContrato.set(false);
        this.toastService.error(err?.error?.detail ?? 'No se pudo subir el archivo');
      },
    });
    input.value = '';
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
      contrato: 'El contrato de separación aún no se ha subido.',
      contrato_firmado: 'El contrato firmado aún no se ha subido.',
      dni_frente: 'No hay foto del DNI (frente).',
      dni_reverso: 'No hay foto del DNI (reverso).',
      voucher: 'No hay voucher adjunto.',
    };
    return mapa[clave];
  }
}