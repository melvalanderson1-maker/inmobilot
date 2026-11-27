import { CommonModule } from '@angular/common';
import { Component, OnInit, signal } from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';

import { ClienteService } from '../../core/services/cliente.service';
import { ToastService } from '../../core/services/toast.service';
import { ClienteDetalle, ClienteUpdate } from '../../core/models';

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

  /** true = se pueden cambiar los DNI desde el detalle. Poner en false al terminar la carga de datos. */
  readonly permitirEditarArchivos = true;
  reemplazandoDni = signal<string | null>(null);

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


  onReemplazarDni(event: Event, destino: 'titular_frente' | 'titular_reverso' | 'conyuge_frente' | 'conyuge_reverso'): void {
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

    const formData = new FormData();
    formData.append('archivo', archivo);
    this.reemplazandoDni.set(destino);

    this.clienteService.subirArchivo(formData).subscribe({
      next: (res) => {
        const c = this.cliente();
        let payload: Record<string, unknown>;

        if (destino === 'titular_frente') payload = { dni_frente_url: res.url };
        else if (destino === 'titular_reverso') payload = { dni_reverso_url: res.url };
        else {
          const cy = c?.conyuge;
          if (!cy) {
            this.reemplazandoDni.set(null);
            return;
          }
          // El backend reemplaza el cónyuge completo: se envían todos sus datos
          payload = {
            conyuge: {
              nombres: cy.nombres,
              apellidos: cy.apellidos,
              numero_documento: cy.numero_documento,
              telefono: cy.telefono ?? null,
              direccion: (cy as unknown as { direccion?: string | null }).direccion ?? null,
              dni_frente_url: destino === 'conyuge_frente' ? res.url : cy.dni_frente_url ?? null,
              dni_reverso_url: destino === 'conyuge_reverso' ? res.url : cy.dni_reverso_url ?? null,
            },
          };
        }

        this.clienteService.actualizar(this.idCliente, payload as unknown as ClienteUpdate).subscribe({
          next: () => {
            this.reemplazandoDni.set(null);
            this.toastService.exito('Archivo actualizado');
            this.cargar();
          },
          error: (err) => {
            this.reemplazandoDni.set(null);
            this.toastService.error(err?.error?.detail ?? 'No se pudo guardar el archivo');
          },
        });
      },
      error: (err) => {
        this.reemplazandoDni.set(null);
        this.toastService.error(err?.error?.detail ?? 'No se pudo subir el archivo');
      },
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


