import { CommonModule } from '@angular/common';
import { Component, OnInit, OnDestroy, signal } from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import { FormsModule } from '@angular/forms';

import { VentaService } from '../../core/services/venta.service';
import { SocketService } from '../../core/services/socket.service';
import { ToastService } from '../../core/services/toast.service';
import { Venta, DocumentoUbicacionCreate } from '../../core/models';

@Component({
  selector: 'app-venta-detalle',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './venta-detalle.component.html',
  styleUrl: './venta-detalle.component.css',
})
export class VentaDetalleComponent implements OnInit, OnDestroy {
  venta = signal<Venta | null>(null);
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

  constructor(
    private ventaService: VentaService,
    private socket: SocketService,
    private toastService: ToastService,
    private route: ActivatedRoute,
    private router: Router
  ) {}

  ngOnInit(): void {
    this.idVenta = Number(this.route.snapshot.paramMap.get('id'));
    this.cargar();

    this.socket.conectar();
    this.socket.onEvento.subscribe((evento) => {
      if (evento.evento === 'venta:nueva' || evento.evento === 'venta:actualizada') {
        const data = evento.data as { id?: number };
        if (data?.id === this.idVenta) this.cargar();
      }
    });
  }

  ngOnDestroy(): void {
    this.socket.desconectar();
  }

  cargar(): void {
    this.cargando.set(true);
    this.ventaService.obtener(this.idVenta).subscribe({
      next: (res) => {
        this.venta.set(res);
        this.cargando.set(false);
      },
      error: () => this.cargando.set(false),
    });
  }

  volver(): void {
    this.router.navigate(['/dashboard/separaciones']);
  }

  nombreDocumento(): string {
    const v = this.venta();
    if (!v) return 'Documento';
    return v.forma_pago === 'contado' ? 'Minuta' : 'Contrato Preparatorio';
  }

  generarDocumento(): void {
    this.procesando.set(true);
    this.ventaService.generarDocumento(this.idVenta).subscribe({
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

  abrirUbicacion(): void {
    this.ubicacionForm = {
      tipo_documento: this.venta()?.forma_pago === 'contado' ? 'minuta' : 'contrato_preparatorio',
      ubicacion: 'notaria',
      estado_tramite: 'en_proceso',
    };
    this.mostrarUbicacion.set(true);
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

  etiquetaEstado(estado: string): string {
    const mapa: Record<string, string> = {
      iniciada: 'Iniciada',
      documento_generado: 'Documento generado',
      documento_firmado: 'Documento firmado',
      escriturada: 'Escriturada',
      cancelada: 'Cancelada',
      anulada: 'Anulada',
    };
    return mapa[estado] ?? estado;
  }

  etiquetaUbicacion(u: string): string {
    const mapa: Record<string, string> = {
      notaria: 'Notaría', juez_de_paz: 'Juez de Paz',
      municipalidad: 'Municipalidad', archivo_central: 'Archivo Central', otro: 'Otro',
    };
    return mapa[u] ?? u;
  }
}