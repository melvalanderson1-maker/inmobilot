import { CommonModule } from '@angular/common';
import { Component, OnInit, signal } from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';

import { ClienteService } from '../../core/services/cliente.service';
import { ToastService } from '../../core/services/toast.service';
import { ClienteDetalle } from '../../core/models';

@Component({
  selector: 'app-cliente-detalle',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './cliente-detalle.component.html',
  styleUrl: './cliente-detalle.component.css',
})
export class ClienteDetalleComponent implements OnInit {
  cliente = signal<ClienteDetalle | null>(null);
  cargando = signal(false);
  idCliente!: number;

  registrandoConyuge = signal(false);

  constructor(
    private clienteService: ClienteService,
    private toastService: ToastService,
    private route: ActivatedRoute,
    private router: Router
  ) {}

  ngOnInit(): void {
    // Suscripción al parámetro: al pasar de un cliente a otro la pantalla se recarga
    this.route.paramMap.subscribe((p) => {
      this.idCliente = Number(p.get('id'));
      this.cargar();
    });
  }

  registrarConyugeComoCliente(): void {
    this.registrandoConyuge.set(true);
    this.clienteService.conyugeComoCliente(this.idCliente).subscribe({
      next: (c) => {
        this.registrandoConyuge.set(false);
        this.toastService.exito('Cónyuge registrada como cliente');
        this.router.navigate(['/dashboard/clientes', c.id]);
      },
      error: (err) => {
        this.registrandoConyuge.set(false);
        this.toastService.error(err?.error?.detail ?? 'No se pudo registrar al cónyuge como cliente');
      },
    });
  }

  cargar(): void {
    this.cargando.set(true);
    this.clienteService.obtener(this.idCliente).subscribe({
      next: (res) => {
        this.cliente.set(res);
        this.cargando.set(false);
      },
      error: () => this.cargando.set(false),
    });
  }

  volver(): void {
    this.router.navigate(['/dashboard/clientes']);
  }

  editar(): void {
    this.router.navigate(['/dashboard/clientes', this.idCliente, 'editar']);
  }

  irASeparacion(idSeparacion: number): void {
    this.router.navigate(['/dashboard/separaciones', idSeparacion]);
  }

  nombreCompleto(): string {
    const c = this.cliente();
    if (!c) return '';
    return c.tipo_persona === 'juridica' ? c.razon_social || c.nombres : `${c.nombres} ${c.apellidos}`;
  }

  etiquetaEstadoSep(estado: string): string {
    const mapa: Record<string, string> = {
      pendiente_caja: 'Pendiente Caja',
      pendiente_facturacion: 'Pendiente Facturación',
      vigente: 'Vigente',
      vencida: 'Vencida',
      convertida: 'Convertida',
      devolucion_pendiente: 'Devolución pendiente',
      devuelta: 'Devuelta',
      rechazada: 'Rechazada',
    };
    return mapa[estado] ?? estado;
  }
}