import { CommonModule } from '@angular/common';
import { Component, OnInit, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';

import { SeparacionService } from '../../core/services/separacion.service';
import { ClienteService } from '../../core/services/cliente.service';
import { VentaService } from '../../core/services/venta.service';
import { ToastService } from '../../core/services/toast.service';
import { Separacion, FormaPago, Cliente, VentaClienteIn } from '../../core/models';

@Component({
  selector: 'app-venta-form',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './venta-form.component.html',
  styleUrl: './venta-form.component.css',
})
export class VentaFormComponent implements OnInit {
  idSeparacion!: number;
  separacion = signal<Separacion | null>(null);
  cargando = signal(false);
  guardando = signal(false);
  error = signal<string | null>(null);

  formaPago: FormaPago = 'contado';
  precioTotal: number | null = null;

  pagosPrevios: { monto: number | null; fecha: string }[] = [{ monto: null, fecha: '' }];

  datosCredito = {
    inicial_monto: null as number | null,
    fecha_deposito: '',
    numero_operacion: '',
    plazo_anios: 2,
    tasa_interes: 25,
  };

  agregarSegundoComprador = signal(false);
  documentoBusqueda2 = '';
  buscandoCliente2 = signal(false);
  cliente2 = signal<Cliente | null>(null);
  cliente2NoEncontrado = signal(false);

  constructor(
    private separacionService: SeparacionService,
    private clienteService: ClienteService,
    private ventaService: VentaService,
    private toastService: ToastService,
    private route: ActivatedRoute,
    private router: Router
  ) {}

  ngOnInit(): void {
    this.idSeparacion = Number(this.route.snapshot.paramMap.get('id'));
    this.cargar();
  }

  cargar(): void {
    this.cargando.set(true);
    this.separacionService.obtener(this.idSeparacion).subscribe({
      next: (res) => {
        this.separacion.set(res);
        this.precioTotal = res.lote?.precio_total_contado ? Number(res.lote.precio_total_contado) : null;
        if (res.tipo_pago) this.formaPago = res.tipo_pago;
        this.cargando.set(false);
      },
      error: () => this.cargando.set(false),
    });
  }

  buscarCliente2(): void {
    const doc = this.documentoBusqueda2.trim();
    if (!doc) return;
    this.buscandoCliente2.set(true);
    this.cliente2.set(null);
    this.cliente2NoEncontrado.set(false);

    this.clienteService.buscarPorDocumento(doc).subscribe({
      next: (cliente) => {
        this.buscandoCliente2.set(false);
        if (cliente) {
          this.cliente2.set(cliente);
        } else {
          this.cliente2NoEncontrado.set(true);
        }
      },
      error: () => {
        this.buscandoCliente2.set(false);
        this.toastService.error('No se pudo buscar el cliente');
      },
    });
  }

  irACrearCliente2(): void {
    this.router.navigate(['/dashboard/clientes/nuevo'], {
      queryParams: {
        documento: this.documentoBusqueda2.trim(),
        returnTo: `/dashboard/separaciones/${this.idSeparacion}/iniciar-venta`,
      },
    });
  }

  quitarSegundoComprador(): void {
    this.agregarSegundoComprador.set(false);
    this.cliente2.set(null);
    this.cliente2NoEncontrado.set(false);
    this.documentoBusqueda2 = '';
  }

  agregarFilaPago(): void {
    this.pagosPrevios.push({ monto: null, fecha: '' });
  }

  quitarFilaPago(index: number): void {
    this.pagosPrevios.splice(index, 1);
  }

  mensajeFaltante(): string | null {
    if (!this.precioTotal || this.precioTotal <= 0) return 'Indica el precio total de la venta';
    if (this.agregarSegundoComprador() && !this.cliente2()) {
      return 'Busca o crea el segundo comprador, o quita esa sección';
    }
    return null;
  }

  guardar(): void {
    const faltante = this.mensajeFaltante();
    if (faltante) {
      this.error.set(faltante);
      return;
    }
    const sep = this.separacion();
    if (!sep) return;

    this.error.set(null);
    this.guardando.set(true);

    const clientes: VentaClienteIn[] = [{ id_cliente: sep.id_cliente, rol: 'titular' }];
    const c2 = this.cliente2();
    if (c2) {
      clientes.push({ id_cliente: c2.id, rol: 'conyuge' });
    }

    const pagosValidos = this.pagosPrevios.filter((p) => p.monto && p.fecha);

    this.ventaService
      .crearDesdeSeparacion(this.idSeparacion, {
        forma_pago: this.formaPago,
        precio_total: this.precioTotal!,
        clientes,
        pagos_previos: this.formaPago === 'contado' ? pagosValidos as any : undefined,
        datos_credito:
          this.formaPago === 'credito' && this.datosCredito.inicial_monto
            ? {
                inicial_monto: this.datosCredito.inicial_monto,
                fecha_deposito: this.datosCredito.fecha_deposito,
                numero_operacion: this.datosCredito.numero_operacion,
                plazo_anios: this.datosCredito.plazo_anios,
                tasa_interes: this.datosCredito.tasa_interes,
              }
            : undefined,
      })
      .subscribe({
        next: (venta) => {
          this.guardando.set(false);
          this.toastService.exito('Venta iniciada correctamente');
          this.router.navigate(['/dashboard/ventas', venta.id]);
        },
        error: (err) => {
          this.guardando.set(false);
          const mensaje = err?.error?.detail ?? 'No se pudo iniciar la venta';
          this.error.set(mensaje);
          this.toastService.error(mensaje);
        },
      });
  }

  cancelar(): void {
    this.router.navigate(['/dashboard/separaciones', this.idSeparacion]);
  }
}