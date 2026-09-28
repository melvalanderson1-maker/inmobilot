import { CommonModule } from '@angular/common';
import { Component, OnInit, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';

import { ApiService } from '../../core/services/api.service';
import { ClienteService } from '../../core/services/cliente.service';
import { SeparacionService } from '../../core/services/separacion.service';
import { ToastService } from '../../core/services/toast.service';
import { Cliente, FormaPago, Lote, Manzana } from '../../core/models';

@Component({
  selector: 'app-separacion-form',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './separacion-form.component.html',
  styleUrl: './separacion-form.component.css',
})
export class SeparacionFormComponent implements OnInit {
  idProyecto: number | null = null;
  lotesLibres = signal<Lote[]>([]);
  manzanas = signal<Manzana[]>([]);
  loteSeleccionado = signal<Lote | null>(null);
  guardando = signal(false);
  error = signal<string | null>(null);

  documentoBusqueda = '';
  buscandoCliente = signal(false);
  clienteEncontrado = signal<Cliente | null>(null);
  clienteNoEncontrado = signal(false);

  form = {
    id_lote: null as number | null,
    fecha_inicio: this.hoy(),
    fecha_vencimiento: '',
    importe: null as number | null,
    motivo: '',
    tipo_pago: null as FormaPago | null,
    notas: '',
    agenda_fecha: '',
  };

  subiendoDniFrente = signal(false);
  subiendoDniReverso = signal(false);
  subiendoVoucher = signal(false);
  dniFrenteUrl: string | null = null;
  dniReversoUrl: string | null = null;
  voucherUrl: string | null = null;

  constructor(
    private api: ApiService,
    private clienteService: ClienteService,
    private separacionService: SeparacionService,
    private toastService: ToastService,
    private route: ActivatedRoute,
    private router: Router
  ) {}

  ngOnInit(): void {
    this.route.queryParams.subscribe((params) => {
      const id = Number(params['id_proyecto']);
      this.idProyecto = id || null;
      if (this.idProyecto) this.cargarLotesLibres();

      // Volvemos desde "crear cliente nuevo" con el cliente ya creado
      const idCliente = Number(params['id_cliente']);
      if (idCliente) {
        this.clienteService.obtener(idCliente).subscribe((cliente) => {
          this.clienteEncontrado.set(cliente);
          this.clienteNoEncontrado.set(false);
          this.dniFrenteUrl = cliente.dni_frente_url ?? null;
          this.dniReversoUrl = cliente.dni_reverso_url ?? null;
        });
      }
    });
  }

  private hoy(): string {
    return new Date().toISOString().slice(0, 10);
  }

  cargarLotesLibres(): void {
    this.api.get<Lote[]>('/lotes', { id_proyecto: this.idProyecto }).subscribe((res) => {
      this.lotesLibres.set(res.filter((l) => l.estado === 'libre'));
    });
    this.api.get<Manzana[]>(`/proyectos/${this.idProyecto}/manzanas`).subscribe((res) => this.manzanas.set(res));
  }

  onLoteSeleccionado(): void {
    this.loteSeleccionado.set(this.lotesLibres().find((l) => l.id === this.form.id_lote) ?? null);
  }

  nombreManzana(lote: Lote): string {
    const manzana = this.manzanas().find((m) => m.id === lote.id_manzana);
    return manzana ? manzana.nombre : '—';
  }

  buscarCliente(): void {
    const doc = this.documentoBusqueda.trim();
    if (!doc) return;
    this.buscandoCliente.set(true);
    this.clienteEncontrado.set(null);
    this.clienteNoEncontrado.set(false);

    this.clienteService.buscarPorDocumento(doc).subscribe({
      next: (cliente) => {
        this.buscandoCliente.set(false);
        if (cliente) {
          this.clienteEncontrado.set(cliente);
          this.dniFrenteUrl = cliente.dni_frente_url ?? null;
          this.dniReversoUrl = cliente.dni_reverso_url ?? null;
        } else {
          this.clienteNoEncontrado.set(true);
        }
      },
      error: () => {
        this.buscandoCliente.set(false);
        this.toastService.error('No se pudo buscar el cliente');
      },
    });
  }

  irACrearCliente(): void {
    this.router.navigate(['/dashboard/clientes/nuevo'], {
      queryParams: {
        documento: this.documentoBusqueda.trim(),
        returnTo: '/dashboard/separaciones/nueva',
        id_proyecto: this.idProyecto,
      },
    });
  }

  cambiarCliente(): void {
    this.clienteEncontrado.set(null);
    this.clienteNoEncontrado.set(false);
    this.documentoBusqueda = '';
    this.dniFrenteUrl = null;
    this.dniReversoUrl = null;
  }

  private subirArchivo(archivo: File, destino: 'frente' | 'reverso' | 'voucher'): void {
    const tiposPermitidos = ['image/jpeg', 'image/png', 'application/pdf'];
    if (!tiposPermitidos.includes(archivo.type)) {
      this.toastService.error('Formato no permitido (usa JPG, PNG o PDF)');
      return;
    }
    if (archivo.size > 8 * 1024 * 1024) {
      this.toastService.error('El archivo debe pesar menos de 8MB');
      return;
    }

    const formData = new FormData();
    formData.append('archivo', archivo);

    const flag =
      destino === 'frente' ? this.subiendoDniFrente : destino === 'reverso' ? this.subiendoDniReverso : this.subiendoVoucher;
    flag.set(true);

    this.separacionService.subirArchivo(formData).subscribe({
      next: (res) => {
        flag.set(false);
        if (destino === 'frente') this.dniFrenteUrl = res.url;
        if (destino === 'reverso') this.dniReversoUrl = res.url;
        if (destino === 'voucher') this.voucherUrl = res.url;
      },
      error: (err) => {
        flag.set(false);
        this.toastService.error(err?.error?.detail ?? 'No se pudo subir el archivo');
      },
    });
  }

  onDniFrenteSeleccionado(event: Event): void {
    const input = event.target as HTMLInputElement;
    const archivo = input.files?.[0];
    if (archivo) this.subirArchivo(archivo, 'frente');
    input.value = '';
  }

  onDniReversoSeleccionado(event: Event): void {
    const input = event.target as HTMLInputElement;
    const archivo = input.files?.[0];
    if (archivo) this.subirArchivo(archivo, 'reverso');
    input.value = '';
  }

  onVoucherSeleccionado(event: Event): void {
    const input = event.target as HTMLInputElement;
    const archivo = input.files?.[0];
    if (archivo) this.subirArchivo(archivo, 'voucher');
    input.value = '';
  }

  guardar(): void {
    const cliente = this.clienteEncontrado();
    if (!cliente) {
      this.error.set('Busca o crea el cliente antes de continuar');
      return;
    }
    if (!this.form.id_lote) {
      this.error.set('Selecciona el lote');
      return;
    }
    if (!this.form.fecha_vencimiento) {
      this.error.set('Indica la fecha de vencimiento de la separación');
      return;
    }
    if (!this.form.importe || this.form.importe <= 0) {
      this.error.set('Indica el importe separado');
      return;
    }
    if (!this.dniFrenteUrl || !this.dniReversoUrl || !this.voucherUrl) {
      this.error.set('Sube el DNI (ambas caras) y el voucher antes de guardar');
      return;
    }

    this.error.set(null);
    this.guardando.set(true);

    this.separacionService
      .crear({
        id_lote: this.form.id_lote,
        id_cliente: cliente.id,
        fecha_inicio: this.form.fecha_inicio,
        fecha_vencimiento: this.form.fecha_vencimiento,
        importe: this.form.importe,
        motivo: this.form.motivo || undefined,
        tipo_pago: this.form.tipo_pago || undefined,
        notas: this.form.notas || undefined,
        agenda_fecha: this.form.agenda_fecha ? new Date(this.form.agenda_fecha).toISOString() : undefined,
        dni_frente_url: this.dniFrenteUrl,
        dni_reverso_url: this.dniReversoUrl,
        voucher_url: this.voucherUrl,
      })
      .subscribe({
        next: (sep) => {
          this.guardando.set(false);
          this.toastService.exito('Separación registrada. Caja debe validar el voucher.');
          this.router.navigate(['/dashboard/separaciones', sep.id]);
        },
        error: (err) => {
          this.guardando.set(false);
          const mensaje = err?.error?.detail ?? 'No se pudo registrar la separación';
          this.error.set(mensaje);
          this.toastService.error(mensaje);
        },
      });
  }

  cancelar(): void {
    this.router.navigate(['/dashboard/separaciones']);
  }
}