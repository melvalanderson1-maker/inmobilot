import { DecimalPipe, SlicePipe, TitleCasePipe } from '@angular/common';
import { Component, OnDestroy, OnInit, computed, inject, signal } from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { Subscription } from 'rxjs';

import { VentaService } from '../../core/services/venta.service';
import { SocketService } from '../../core/services/socket.service';
import { ToastService } from '../../core/services/toast.service';
import { ContratoService } from '../../core/services/contrato.service';
import { Venta, DocumentoUbicacion, DocumentoUbicacionCreate, CronogramaCuota } from '../../core/models';

type EstadoPaso = 'hecho' | 'actual' | 'pendiente';


interface DocTramite {
  tipo: string;
  etiqueta: string;
  actual: DocumentoUbicacion | null;
  historial: DocumentoUbicacion[];
}

@Component({
  selector: 'app-venta-detalle',
  standalone: true,
  imports: [FormsModule, DecimalPipe, TitleCasePipe, SlicePipe],
  templateUrl: './venta-detalle.component.html',
  styleUrl: './venta-detalle.component.css',
})
export class VentaDetalleComponent implements OnInit, OnDestroy {
  private readonly ventaService = inject(VentaService);
  private readonly contratoService = inject(ContratoService);
  private readonly socket = inject(SocketService);
  private readonly toastService = inject(ToastService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);

  private suscripcionSocket?: Subscription;

  venta = signal<Venta | null>(null);
  cronograma = signal<CronogramaCuota[]>([]);
  cargando = signal(false);
  procesando = signal(false);
  idVenta!: number;

  mostrarUbicacion = signal(false);
  ubicacionForm: DocumentoUbicacionCreate = {
    tipo_documento: 'minuta',
    ubicacion: 'notaria',
    estado_tramite: 'en_proceso',
  };

  subiendoFirmado = signal(false);

  subiendoLegal = signal<'escritura' | 'titulo' | null>(null);
    readonly estadosTramite = [
    { valor: 'pendiente', etiqueta: 'Pendiente' },
    { valor: 'en_proceso', etiqueta: 'En proceso' },
    { valor: 'concretado', etiqueta: 'Concretado' },
  ];

  /** Quién firma por la empresa en el documento que se va a generar */
  firmante = signal<'gerente' | 'apoderado'>('gerente');

  // ---------- Datos derivados ----------

  /** Línea de tiempo: cada paso se marca según el documento realmente subido */
  pasos = computed<{ etiqueta: string; estado: EstadoPaso }[]>(() => {
    const v = this.venta();
    if (!v) return [];
    const fin = v.estado === 'finalizada';
    const hechos = [
      true,
      !!v.documento_generado_url || fin,
      !!v.documento_firmado_url || fin,
      !!v.escritura_url || v.estado === 'escriturada' || fin,
      !!v.titulo_url || fin,
      fin,
    ];
    const etiquetas = ['Iniciada', 'Documento generado', 'Documento firmado', 'Escriturada', 'Titulada', 'Finalizada'];
    const actual = hechos.findIndex((h) => !h);
    return etiquetas.map((etiqueta, i) => ({
      etiqueta,
      estado: (hechos[i] ? 'hecho' : i === actual ? 'actual' : 'pendiente') as EstadoPaso,
    }));
  });

  
  anulada = computed(() => {
    const e = this.venta()?.estado;
    return e === 'cancelada' || e === 'anulada';
  });

    /** Un renglón por documento; "actual" = el último registro de ese documento */
  documentos = computed<DocTramite[]>(() => {
    const v = this.venta();
    if (!v) return [];
    const base = v.forma_pago === 'contado' ? 'minuta' : 'contrato_preparatorio';
    const ordenadas = [...(v.ubicaciones ?? [])].sort(
      (a, b) => (b.created_at ?? '').localeCompare(a.created_at ?? '') || b.id - a.id
    );
    return [base, 'escritura', 'titulo'].map((tipo) => {
      const historial = ordenadas.filter((u) => u.tipo_documento === tipo);
      return { tipo, etiqueta: this.etiquetaTipoDocumento(tipo), actual: historial[0] ?? null, historial };
    });
  });

  pagosPrevios = computed(() => (this.venta()?.pagos_previos ?? []).map((p) => ({ monto: Number(p.monto), fecha: p.fecha })));

  totalPagado = computed(() => this.pagosPrevios().reduce((acc, p) => acc + p.monto, 0));

  saldo = computed(() => {
    const v = this.venta();
    if (!v) return 0;
    return Math.max(Number(v.precio_total) - this.totalPagado(), 0);
  });

  porcentajePagado = computed(() => {
    const v = this.venta();
    const total = Number(v?.precio_total ?? 0);
    if (!total) return 0;
    return Math.min(Math.round((this.totalPagado() / total) * 100), 100);
  });

  plazoMeses = computed<number | null>(() => {
    const dc = this.venta()?.datos_credito;
    if (!dc) return null;
    if (dc.plazo_meses != null) return Number(dc.plazo_meses);
    if (dc.plazo_anios != null) return Number(dc.plazo_anios) * 12;
    return null;
  });

  interesAnual = computed<number>(() => {
    const dc = this.venta()?.datos_credito;
    if (!dc) return 0;
    if (dc.tea_financiamiento != null) return Number(dc.tea_financiamiento);
    return (this.plazoMeses() ?? 0) > 24 ? 20 : 0;
  });

  cuotasPagadas = computed(() => this.cronograma().filter((c) => c.estado === 'pagada').length);

  progresoCuotas = computed(() => {
    const total = this.cronograma().length;
    return total ? Math.round((this.cuotasPagadas() / total) * 100) : 0;
  });

  totalCronograma = computed(() => this.cronograma().reduce((acc, c) => acc + Number(c.monto_cuota), 0));

  totalCobrado = computed(() => this.cronograma().reduce((acc, c) => acc + Number(c.monto_pagado ?? 0), 0));

  // ---------- Ciclo de vida ----------

  ngOnInit(): void {
    this.idVenta = Number(this.route.snapshot.paramMap.get('id'));
    this.cargar();

    this.socket.conectar();
    this.suscripcionSocket = this.socket.onEvento.subscribe((evento) => {
      if (evento.evento === 'venta:nueva' || evento.evento === 'venta:actualizada') {
        const data = evento.data as { id?: number };
        if (data?.id === this.idVenta) this.cargar();
      }
    });
  }

  ngOnDestroy(): void {
    this.suscripcionSocket?.unsubscribe();
    this.socket.desconectar();
  }

  cargar(): void {
    this.cargando.set(true);
    this.ventaService.obtener(this.idVenta).subscribe({
      next: (res) => {
        this.venta.set(res);
        this.cargando.set(false);
        if (res.id_contrato && res.forma_pago === 'credito') {
          this.contratoService.cronograma(res.id_contrato).subscribe((c) => this.cronograma.set(c));
        } else {
          this.cronograma.set([]);
        }
      },
      error: () => this.cargando.set(false),
    });
  }

  // ---------- Navegación ----------

  volver(): void {
    this.router.navigate(['/dashboard/contratos']);
  }

  verSeparacion(): void {
    const id = this.venta()?.id_separacion;
    if (id) this.router.navigate(['/dashboard/separaciones', id]);
  }

  verCronogramaYPagos(): void {
    const id = this.venta()?.id_contrato;
    if (id) this.router.navigate(['/dashboard/contratos'], { queryParams: { abrir: id } });
  }

  // ---------- Documento ----------

  nombreDocumento(): string {
    const v = this.venta();
    if (!v) return 'Documento';
    return v.forma_pago === 'contado' ? 'Minuta' : 'Contrato Preparatorio';
  }

  generarDocumento(): void {
    this.procesando.set(true);
    this.ventaService.generarDocumento(this.idVenta, this.firmante()).subscribe({
      next: () => {
        this.procesando.set(false);
        this.toastService.exito(`${this.nombreDocumento()} generado correctamente`);
        this.cargar();
      },
      error: (err) => {
        this.procesando.set(false);
        this.toastService.error(err?.error?.detail ?? 'No se pudo generar el documento');
      },
    });
  }

  onDocumentoFirmadoSeleccionado(event: Event): void {
    const input = event.target as HTMLInputElement;
    const archivo = input.files?.[0];
    if (!archivo) return;

    const formData = new FormData();
    formData.append('archivo', archivo);
    this.subiendoFirmado.set(true);

    this.ventaService.subirArchivo(formData).subscribe({
      next: (res) => {
        this.ventaService.subirDocumentoFirmado(this.idVenta, res.url).subscribe({
          next: () => {
            this.subiendoFirmado.set(false);
            this.toastService.exito('Documento firmado registrado');
            this.cargar();
          },
          error: (err) => {
            this.subiendoFirmado.set(false);
            this.toastService.error(err?.error?.detail ?? 'No se pudo guardar el documento firmado');
          },
        });
      },
      error: (err) => {
        this.subiendoFirmado.set(false);
        this.toastService.error(err?.error?.detail ?? 'No se pudo subir el archivo');
      },
    });
    input.value = '';
  }

  registrarContrato(): void {
    this.procesando.set(true);
    this.ventaService.registrarContrato(this.idVenta).subscribe({
      next: () => {
        this.procesando.set(false);
        this.toastService.exito('Contrato registrado. El lote pasó a vendido.');
        this.cargar();
      },
      error: (err) => {
        this.procesando.set(false);
        this.toastService.error(err?.error?.detail ?? 'No se pudo registrar el contrato');
      },
    });
  }


    onDocumentoLegalSeleccionado(event: Event, tipo: 'escritura' | 'titulo'): void {
    const input = event.target as HTMLInputElement;
    const archivo = input.files?.[0];
    if (!archivo) return;

    const formData = new FormData();
    formData.append('archivo', archivo);
    this.subiendoLegal.set(tipo);

    this.ventaService.subirArchivo(formData).subscribe({
      next: (res) => {
        this.ventaService.subirDocumentoLegal(this.idVenta, tipo, res.url).subscribe({
          next: () => {
            this.subiendoLegal.set(null);
            this.toastService.exito(tipo === 'escritura' ? 'Escritura pública registrada' : 'Título de propiedad registrado');
            this.cargar();
          },
          error: (err) => {
            this.subiendoLegal.set(null);
            this.toastService.error(err?.error?.detail ?? 'No se pudo guardar el documento');
          },
        });
      },
      error: (err) => {
        this.subiendoLegal.set(null);
        this.toastService.error(err?.error?.detail ?? 'No se pudo subir el archivo');
      },
    });
    input.value = '';
  }

  // ---------- Ubicación física ----------

  abrirUbicacion(): void {
    this.ubicarDocumento(this.venta()?.forma_pago === 'contado' ? 'minuta' : 'contrato_preparatorio');
  }

  /** Abre el formulario con el documento ya elegido y, si existe, con su última ubicación */
  ubicarDocumento(tipo: string): void {
    const actual = this.documentos().find((d) => d.tipo === tipo)?.actual;
    this.ubicacionForm = {
      tipo_documento: tipo,
      ubicacion: actual?.ubicacion ?? 'notaria',
      notaria_nombre: actual?.notaria_nombre,
      estado_tramite: actual?.estado_tramite ?? 'en_proceso',
      numero_tramite: actual?.numero_tramite,
      numero_titulo: actual?.numero_titulo,
    };
    this.mostrarUbicacion.set(true);
  }

  /** Cambio de estado en un clic: repite la última ubicación con el nuevo estado */
  cambiarTramite(tipo: string, estado: string): void {
    const actual = this.documentos().find((d) => d.tipo === tipo)?.actual;
    if (!actual) {
      this.ubicarDocumento(tipo);
      return;
    }
    if (actual.estado_tramite === estado) return;
    this.procesando.set(true);
    this.ventaService
      .registrarUbicacion(this.idVenta, {
        tipo_documento: tipo,
        ubicacion: actual.ubicacion,
        notaria_nombre: actual.notaria_nombre,
        numero_tramite: actual.numero_tramite,
        numero_titulo: actual.numero_titulo,
        estado_tramite: estado,
      })
      .subscribe({
        next: () => {
          this.procesando.set(false);
          this.toastService.exito(`${this.etiquetaTipoDocumento(tipo)}: ${this.etiquetaTramite(estado)}`);
          this.cargar();
        },
        error: (err) => {
          this.procesando.set(false);
          this.toastService.error(err?.error?.detail ?? 'No se pudo cambiar el estado');
        },
      });
  }

  guardarUbicacion(): void {
    if (!this.ubicacionForm.ubicacion) {
      this.toastService.error('Indica dónde está el documento');
      return;
    }
    this.procesando.set(true);
    this.ventaService.registrarUbicacion(this.idVenta, this.ubicacionForm).subscribe({
      next: () => {
        this.procesando.set(false);
        this.mostrarUbicacion.set(false);
        this.toastService.exito('Ubicación del documento registrada');
        this.cargar();
      },
      error: (err) => {
        this.procesando.set(false);
        this.toastService.error(err?.error?.detail ?? 'No se pudo registrar la ubicación');
      },
    });
  }

  // ---------- Etiquetas ----------

  etiquetaEstado(estado: string): string {
    const mapa: Record<string, string> = {
      iniciada: 'Iniciada',
      documento_generado: 'Documento generado',
      documento_firmado: 'Documento firmado',
      escriturada: 'Escriturada',
      finalizada: 'Finalizada',
      cancelada: 'Cancelada',
      anulada: 'Anulada',
    };
    return mapa[estado] ?? estado;
  }

  etiquetaUbicacion(u: string): string {
    const mapa: Record<string, string> = {
      notaria: 'Notaría',
      juez_de_paz: 'Juez de Paz',
      municipalidad: 'Municipalidad',
      archivo_central: 'Archivo Central',
      otro: 'Otro',
    };
    return mapa[u] ?? u;
  }

  etiquetaTipoDocumento(t: string): string {
    const mapa: Record<string, string> = {
      minuta: 'Minuta',
      contrato_preparatorio: 'Contrato Preparatorio',
      escritura: 'Escritura Pública',
      titulo: 'Título',
    };
    return mapa[t] ?? t;
  }

  etiquetaTramite(t: string): string {
    const mapa: Record<string, string> = {
      en_proceso: 'En proceso',
      pendiente: 'Pendiente',
      concretado: 'Concretado',
    };
    return mapa[t] ?? t;
  }

  etiquetaRol(rol: string): string {
    const mapa: Record<string, string> = { titular: 'Titular', conyuge: 'Cónyuge', copropietario: 'Copropietario' };
    return mapa[rol] ?? rol;
  }

  etiquetaFrecuencia(f: string | undefined): string {
    const mapa: Record<string, string> = {
      mensual: 'Mensual',
      bimestral: 'Bimestral',
      trimestral: 'Trimestral',
      semestral: 'Semestral',
      unico: 'Pago único',
    };
    return f ? (mapa[f] ?? f) : '—';
  }
}