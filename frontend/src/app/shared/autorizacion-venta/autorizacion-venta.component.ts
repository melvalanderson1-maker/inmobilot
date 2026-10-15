import { CommonModule } from '@angular/common';
import { Component, Input, OnDestroy, OnInit, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { Subscription } from 'rxjs';

import { AuthService } from '../../core/services/auth.service';
import { SocketService } from '../../core/services/socket.service';
import { ToastService } from '../../core/services/toast.service';
import { VentaService } from '../../core/services/venta.service';
import { AutorizacionVenta } from '../../core/models';

@Component({
  selector: 'app-autorizacion-venta',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './autorizacion-venta.component.html',
  styleUrl: './autorizacion-venta.component.css',
})
export class AutorizacionVentaComponent implements OnInit, OnDestroy {
  @Input({ required: true }) idSeparacion!: number;

  lista = signal<AutorizacionVenta[]>([]);
  procesando = signal(false);
  respuestas: Record<number, string> = {};
  private sub?: Subscription;

  constructor(
    private ventaService: VentaService,
    private auth: AuthService,
    private socket: SocketService,
    private toastService: ToastService,
    private router: Router
  ) {}

  get rol(): string {
    return this.auth.usuario()?.rol?.clave ?? '';
  }
  get puedeResolver(): boolean {
    return ['admin', 'gerencia'].includes(this.rol);
  }

  ngOnInit(): void {
    this.cargar();
    this.sub = this.socket.onEvento.subscribe((e) => {
      if (e.evento === 'autorizacion:actualizada' && (e.data as any)?.id_separacion === this.idSeparacion) {
        this.cargar();
      }
    });
  }

  ngOnDestroy(): void {
    this.sub?.unsubscribe();
  }

  cargar(): void {
    this.ventaService.listarAutorizaciones(this.idSeparacion).subscribe({
      next: (res) => this.lista.set(res),
      error: () => this.lista.set([]),
    });
  }

  etiqueta(estado: string): string {
    const mapa: Record<string, string> = {
      pendiente: 'Pendiente de gerencia',
      aprobada: 'Aprobada',
      rechazada: 'Rechazada',
      usada: 'Utilizada',
    };
    return mapa[estado] ?? estado;
  }

  resumen(a: AutorizacionVenta): string[] {
    const p = a.propuesta ?? {};
    const dc = p.datos_credito;
    const lineas = [
      `Forma de pago: ${p.forma_pago === 'contado' ? 'Contado' : 'Crédito'}`,
      `Precio total: S/ ${Number(p.precio_total).toFixed(2)}`,
    ];
    if (dc) {
      const tea = dc.tea_financiamiento ?? (dc.plazo_meses > 24 ? 20 : 0);
      lineas.push(
        `Inicial: S/ ${Number(dc.inicial_monto).toFixed(2)}`,
        `Plazo: ${dc.plazo_meses} meses · pagos ${dc.frecuencia_cuota}`,
        `Interés del financiamiento: ${tea}% anual`
      );
      if (dc.observaciones) lineas.push(`Observaciones: ${dc.observaciones}`);
    }
    return lineas;
  }

  resolver(a: AutorizacionVenta, aprobar: boolean): void {
    this.procesando.set(true);
    this.ventaService.resolverAutorizacion(a.id, aprobar, this.respuestas[a.id]).subscribe({
      next: () => {
        this.procesando.set(false);
        this.toastService.exito(aprobar ? 'Autorización aprobada' : 'Autorización rechazada');
        this.cargar();
      },
      error: (err) => {
        this.procesando.set(false);
        this.toastService.error(err?.error?.detail ?? 'No se pudo resolver la solicitud');
      },
    });
  }

  crearVenta(a: AutorizacionVenta): void {
    this.procesando.set(true);
    this.ventaService.crearDesdeAutorizacion(a.id).subscribe({
      next: (venta) => {
        this.procesando.set(false);
        this.toastService.exito('Venta creada con las condiciones autorizadas');
        this.router.navigate(['/dashboard/contratos/venta', venta.id]);
      },
      error: (err) => {
        this.procesando.set(false);
        this.toastService.error(err?.error?.detail ?? 'No se pudo crear la venta');
      },
    });
  }

  irAVenta(a: AutorizacionVenta): void {
    if (a.id_venta) this.router.navigate(['/dashboard/contratos/venta', a.id_venta]);
  }
}