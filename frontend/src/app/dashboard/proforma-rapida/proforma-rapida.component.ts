import { CommonModule } from '@angular/common';
import { Component, OnInit, computed, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';

import { ApiService } from '../../core/services/api.service';
import { ClienteService } from '../../core/services/cliente.service';
import { ProformaService } from '../../core/services/proforma.service';
import { ToastService } from '../../core/services/toast.service';
import { Cliente, FormaPago, Lote, Manzana, Proforma } from '../../core/models';
import { ClienteBuscadorComponent } from '../../shared/cliente-buscador/cliente-buscador.component';

type EstadoVisible = 'vigente' | 'vencida' | 'separada';

@Component({
  selector: 'app-proforma-rapida',
  standalone: true,
  imports: [CommonModule, FormsModule, ClienteBuscadorComponent],
  templateUrl: './proforma-rapida.component.html',
  styleUrl: './proforma-rapida.component.css',
})
export class ProformaRapidaComponent implements OnInit {
  idProyecto: number | null = null;

  lotesTodos = signal<Lote[]>([]);
  lotesLibres = computed(() => this.lotesTodos().filter((l) => l.estado === 'libre'));
  manzanas = signal<Manzana[]>([]);
  loteSeleccionado = signal<Lote | null>(null);

  clienteEncontrado = signal<Cliente | null>(null);
  sinRegistrar = signal(false);
  prospecto = { nombre: '', documento: '', telefono: '' };

  form = {
    id_lote: null as number | null,
    tipo_pago: null as FormaPago | null,
    precio_descontado: null as number | null,
    precio_valido_hasta: this.fechaEnDias(7),
    importe: null as number | null,
  };

  proformas = signal<Proforma[]>([]);
  cargandoLista = signal(false);
  filtro = signal('');
  proformasFiltradas = computed(() => {
    const q = this.filtro().trim().toLowerCase();
    if (!q) return this.proformas();
    return this.proformas().filter((p) =>
      [p.cliente_nombre, p.cliente_documento ?? '', p.cliente_telefono ?? '', p.lote_codigo ?? '']
        .join(' ')
        .toLowerCase()
        .includes(q)
    );
  });

  ultima = signal<Proforma | null>(null);
  guardando = signal(false);
  error = signal<string | null>(null);
  intentoGuardar = signal(false);

  constructor(
    private api: ApiService,
    private clienteService: ClienteService,
    private proformaService: ProformaService,
    private toastService: ToastService,
    private route: ActivatedRoute,
    private router: Router
  ) {}

  ngOnInit(): void {
    this.route.queryParams.subscribe((params) => {
      const id = Number(params['id_proyecto']);
      if (id && id !== this.idProyecto) {
        this.idProyecto = id;
        this.cargarLotes();
        this.cargarLista();
      }
      // Volvemos desde "crear cliente nuevo" con el cliente ya creado
      const idCliente = Number(params['id_cliente']);
      if (idCliente) {
        this.clienteService.obtener(idCliente).subscribe((c) => this.onClienteElegido(c));
      }
    });
  }

  private fechaEnDias(dias: number): string {
    const d = new Date();
    d.setDate(d.getDate() + dias);
    return d.toLocaleDateString('en-CA'); // AAAA-MM-DD en la hora local, no en UTC
  }

  private hoy(): string {
    return this.fechaEnDias(0);
  }

  // ---------------------------------------------------------------- carga --

  cargarLotes(): void {
    this.api.get<Lote[]>('/lotes', { id_proyecto: this.idProyecto }).subscribe((res) => this.lotesTodos.set(res));
    this.api.get<Manzana[]>(`/proyectos/${this.idProyecto}/manzanas`).subscribe((res) => this.manzanas.set(res));
  }

  cargarLista(): void {
    this.cargandoLista.set(true);
    this.proformaService.listar(this.idProyecto!).subscribe({
      next: (res) => {
        this.proformas.set(res);
        this.cargandoLista.set(false);
      },
      error: () => this.cargandoLista.set(false),
    });
  }

  nombreManzana(lote: Lote): string {
    const manzana = this.manzanas().find((m) => m.id === lote.id_manzana);
    return manzana ? manzana.nombre : '—';
  }

  // ----------------------------------------------------------------- lote --

  onLoteSeleccionado(): void {
    const lote = this.lotesTodos().find((l) => l.id === this.form.id_lote) ?? null;
    this.loteSeleccionado.set(lote);
    this.aplicarPrecioReferencia();
  }

  /** Precio de lista que corresponde al tipo de pago elegido */
  precioReferencia(): number | null {
    const l = this.loteSeleccionado();
    if (!l) return null;
    const v =
      this.form.tipo_pago === 'contado' ? l.precio_total_contado
      : this.form.tipo_pago === 'credito' ? l.precio_total_financiado
      : l.precio_total_base;
    const n = Number(v);
    return v != null && Number.isFinite(n) && n > 0 ? n : null;
  }

  etiquetaPrecioReferencia(): string {
    if (this.form.tipo_pago === 'contado') return 'Precio contado (lista)';
    if (this.form.tipo_pago === 'credito') return 'Precio financiado (lista)';
    return 'Precio regular';
  }

  aplicarPrecioReferencia(): void {
    this.form.precio_descontado = this.precioReferencia();
  }

  get descuento(): number | null {
    const ref = this.precioReferencia();
    const p = this.form.precio_descontado;
    if (!ref || !p) return null;
    return ref - p;
  }

  // -------------------------------------------------------------- cliente --

  onClienteElegido(cliente: Cliente): void {
    this.clienteEncontrado.set(cliente);
    this.sinRegistrar.set(false);
  }

  cambiarCliente(): void {
    this.clienteEncontrado.set(null);
  }

  irACrearClienteNuevo(texto: string): void {
    const esNumero = /^\d{6,}$/.test(texto);
    this.router.navigate(['/dashboard/clientes/nuevo'], {
      queryParams: {
        ...(esNumero ? { documento: texto } : {}),
        returnTo: '/dashboard/separaciones/proformas',
        id_proyecto: this.idProyecto,
      },
    });
  }

  // ------------------------------------------------------------- guardar --

  mensajeFaltante(): string | null {
    if (!this.clienteEncontrado() && !(this.sinRegistrar() && this.prospecto.nombre.trim())) {
      return 'Busca al cliente o escribe al menos el nombre del interesado';
    }
    if (!this.form.id_lote) return 'Selecciona el lote';
    if (!this.form.precio_valido_hasta) return 'Indica hasta qué fecha es válido el precio';
    if (this.form.precio_valido_hasta < this.hoy()) return 'La validez del precio no puede ser anterior a hoy';
    const ref = this.precioReferencia();
    if (this.form.precio_descontado && ref && this.form.precio_descontado > ref) {
      return `El precio final no puede superar el ${this.etiquetaPrecioReferencia().toLowerCase()}`;
    }
    return null;
  }

  generar(): void {
    this.intentoGuardar.set(true);
    if (this.mensajeFaltante()) return;

    const cliente = this.clienteEncontrado();
    this.error.set(null);
    this.guardando.set(true);

    this.proformaService
      .crear({
        id_lote: this.form.id_lote!,
        ...(cliente
          ? { id_cliente: cliente.id }
          : {
              prospecto_nombre: this.prospecto.nombre.trim(),
              prospecto_documento: this.prospecto.documento.trim() || undefined,
              prospecto_telefono: this.prospecto.telefono.trim() || undefined,
            }),
        tipo_pago: this.form.tipo_pago || undefined,
        precio_descontado: this.form.precio_descontado ?? undefined,
        precio_valido_hasta: this.form.precio_valido_hasta,
        importe: this.form.importe ?? undefined,
      })
      .subscribe({
        next: (pf) => {
          this.guardando.set(false);
          this.ultima.set(pf);
          this.proformas.update((lista) => [pf, ...lista]);
          this.toastService.exito('Proforma generada');
          if (pf.documento_url) window.open(pf.documento_url, '_blank');
        },
        error: (err) => {
          this.guardando.set(false);
          const mensaje = err?.error?.detail ?? 'No se pudo generar la proforma';
          this.error.set(typeof mensaje === 'string' ? mensaje : 'No se pudo generar la proforma');
          this.toastService.error(this.error()!);
        },
      });
  }

  nueva(): void {
    this.ultima.set(null);
    this.intentoGuardar.set(false);
    this.error.set(null);
    this.clienteEncontrado.set(null);
    this.sinRegistrar.set(false);
    this.prospecto = { nombre: '', documento: '', telefono: '' };
    this.form = { id_lote: null, tipo_pago: null, precio_descontado: null, precio_valido_hasta: this.fechaEnDias(7), importe: null };
    this.loteSeleccionado.set(null);
    this.cargarLotes(); // el estado de los lotes pudo cambiar mientras tanto
  }

  // ---------------------------------------------------------------- lista --

  estadoVisible(pf: Proforma): EstadoVisible {
    if (pf.estado === 'convertida') return 'separada';
    return pf.precio_valido_hasta < this.hoy() ? 'vencida' : 'vigente';
  }

  etiquetaEstado(e: EstadoVisible): string {
    return { vigente: 'Vigente', vencida: 'Precio vencido', separada: 'Separada' }[e];
  }

  fmtFecha(f: string | null | undefined): string {
    if (!f) return '—';
    const [y, m, d] = String(f).slice(0, 10).split('-');
    return d && m && y ? `${d}/${m}/${y}` : String(f);
  }

  etiquetaTipoPago(t: string | null | undefined): string {
    return t === 'contado' ? 'Contado' : t === 'credito' ? 'Crédito' : 'Sin definir';
  }

  /** El cliente decidió separar: se abre la separación con los datos de la proforma */
  separar(pf: Proforma): void {
    this.router.navigate(['/dashboard/separaciones/nueva'], {
      queryParams: { id_proyecto: pf.id_proyecto, id_proforma: pf.id },
    });
  }

  verSeparacion(id: number): void {
    this.router.navigate(['/dashboard/separaciones', id]);
  }

  /** Vuelve a cargar los datos de una proforma en el formulario para emitir una nueva */
  reusar(pf: Proforma): void {
    this.nueva();
    this.form.tipo_pago = (pf.tipo_pago as FormaPago | null) ?? null;
    if (pf.id_cliente) {
      this.clienteService.obtener(pf.id_cliente).subscribe((c) => this.onClienteElegido(c));
    } else {
      this.sinRegistrar.set(true);
      this.prospecto = {
        nombre: pf.cliente_nombre,
        documento: pf.cliente_documento ?? '',
        telefono: pf.cliente_telefono ?? '',
      };
    }
    const lote = this.lotesLibres().find((l) => l.id === pf.id_lote);
    if (lote) {
      this.form.id_lote = lote.id;
      this.onLoteSeleccionado();
    } else {
      this.toastService.error(`El lote ${pf.lote_codigo ?? ''} ya no está libre`);
    }
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  volver(): void {
    this.router.navigate(['/dashboard/separaciones']);
  }
}