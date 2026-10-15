import { CommonModule } from '@angular/common';
import { Component, OnInit, computed, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';

import { SeparacionService } from '../../core/services/separacion.service';
import { ClienteService } from '../../core/services/cliente.service';
import { VentaService } from '../../core/services/venta.service';
import { ToastService } from '../../core/services/toast.service';
import { Separacion, FormaPago, Cliente, VentaClienteIn, VentaCreate, EvaluacionVenta } from '../../core/models';
import { ClienteBuscadorComponent } from '../../shared/cliente-buscador/cliente-buscador.component';

type RolExtra = 'conyuge' | 'copropietario';
interface CompradorExtra {
  cliente: Cliente;
  rol: RolExtra;
}

@Component({
  selector: 'app-venta-form',
  standalone: true,
  imports: [CommonModule, FormsModule, ClienteBuscadorComponent],
  templateUrl: './venta-form.component.html',
  styleUrl: './venta-form.component.css',
})
export class VentaFormComponent implements OnInit {
  readonly MAX_EXTRAS = 3; // titular + 3 = 4 compradores

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
    plazo_meses: 24,
    frecuencia_cuota: 'mensual',
    tasa_interes: 25,
    tea_financiamiento: null as number | null,
    observaciones: '',
  };

  frecuencias = [
    { valor: 'mensual', etiqueta: 'Mensual' },
    { valor: 'bimestral', etiqueta: 'Bimestral' },
    { valor: 'trimestral', etiqueta: 'Trimestral' },
    { valor: 'semestral', etiqueta: 'Semestral' },
    { valor: 'unico', etiqueta: 'Pago único al vencimiento' },
  ];

  // ---- Vista previa de reglas (la calcula el backend) ----
  evaluacion = signal<EvaluacionVenta | null>(null);
  errorEvaluacion = signal<string | null>(null);
  private timer: ReturnType<typeof setTimeout> | null = null;

  // ---- Compradores adicionales ----
  extras = signal<CompradorExtra[]>([]);
  agregando = signal(false);
  conyugeTitular = signal<{ nombres: string; apellidos: string; numero_documento: string } | null>(null);
  creandoConyuge = signal(false);

  idsExcluidos = computed(() => [this.separacion()?.id_cliente ?? 0, ...this.extras().map((e) => e.cliente.id)]);
  puedeAgregarMas = computed(() => this.extras().length < this.MAX_EXTRAS);
  conyugeDisponible = computed(() => {
    const cy = this.conyugeTitular();
    if (!cy) return false;
    return !this.extras().some((e) => e.cliente.numero_documento === cy.numero_documento);
  });

  constructor(
    private separacionService: SeparacionService,
    private clienteService: ClienteService,
    private ventaService: VentaService,
    private toastService: ToastService,
    private route: ActivatedRoute,
    private router: Router
  ) {}

  // ---- Borrador: se conserva al ir a "Crear cliente nuevo" y volver ----

  private claveBorrador(): string {
    return `venta-borrador-${this.idSeparacion}`;
  }

  private guardarBorrador(): void {
    sessionStorage.setItem(
      this.claveBorrador(),
      JSON.stringify({
        formaPago: this.formaPago,
        precioTotal: this.precioTotal,
        pagosPrevios: this.pagosPrevios,
        datosCredito: this.datosCredito,
        extras: this.extras(),
      })
    );
  }

  private restaurarBorrador(): void {
    const crudo = sessionStorage.getItem(this.claveBorrador());
    if (!crudo) return;
    try {
      const b = JSON.parse(crudo);
      this.formaPago = b.formaPago ?? this.formaPago;
      this.precioTotal = b.precioTotal ?? this.precioTotal;
      if (b.pagosPrevios?.length) this.pagosPrevios = b.pagosPrevios;
      if (b.datosCredito) this.datosCredito = { ...this.datosCredito, ...b.datosCredito };
      if (b.extras?.length) this.extras.set(b.extras);
    } catch {
      /* borrador dañado: se ignora */
    }
    sessionStorage.removeItem(this.claveBorrador());
  }

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
        this.restaurarBorrador();
        this.cargando.set(false);
        this.reevaluar();

        this.clienteService.obtener(res.id_cliente).subscribe((titular) => {
          this.conyugeTitular.set(titular.conyuge ?? null);
        });

        const idNuevo = Number(this.route.snapshot.queryParamMap.get('id_cliente'));
        if (idNuevo && idNuevo !== res.id_cliente) {
          this.clienteService.obtener(idNuevo).subscribe((c) => this.agregarComprador(c));
        }
      },
      error: () => this.cargando.set(false),
    });
  }

  // ---- Reglas ----

  get plazoTexto(): string {
    const m = Number(this.datosCredito.plazo_meses) || 0;
    if (m <= 0) return '';
    if (m % 12 === 0) return `${m / 12} año${m / 12 === 1 ? '' : 's'}`;
    return m > 12 ? `${Math.floor(m / 12)} año(s) y ${m % 12} mes(es)` : `${m} mes(es)`;
  }

  reevaluar(): void {
    if (this.timer) clearTimeout(this.timer);
    this.timer = setTimeout(() => this.evaluarAhora(), 350);
  }

  private armarPayload(paraEvaluar: boolean): VentaCreate {
    const sep = this.separacion()!;
    const clientes: VentaClienteIn[] = [
      { id_cliente: sep.id_cliente, rol: 'titular' },
      ...this.extras().map((e) => ({ id_cliente: e.cliente.id, rol: e.rol })),
    ];
    const dc = this.datosCredito;
    const hoy = new Date().toISOString().slice(0, 10);
    const pagosValidos = this.pagosPrevios.filter((p) => p.monto && p.fecha);

    return {
      forma_pago: this.formaPago,
      precio_total: this.precioTotal ?? 0,
      clientes,
      pagos_previos: this.formaPago === 'contado' ? (pagosValidos as any) : undefined,
      datos_credito:
        this.formaPago === 'credito' && dc.inicial_monto
          ? {
              inicial_monto: dc.inicial_monto,
              fecha_deposito: dc.fecha_deposito || (paraEvaluar ? hoy : ''),
              numero_operacion: dc.numero_operacion || (paraEvaluar ? '-' : ''),
              plazo_meses: Number(dc.plazo_meses),
              frecuencia_cuota: dc.frecuencia_cuota,
              tasa_interes: dc.tasa_interes,
              tea_financiamiento: Number(dc.plazo_meses) > 24 && dc.tea_financiamiento != null ? dc.tea_financiamiento : undefined,
              observaciones: dc.observaciones || undefined,
            }
          : undefined,
    };
  }

  private evaluarAhora(): void {
    if (!this.separacion() || !this.precioTotal || this.precioTotal <= 0) {
      this.evaluacion.set(null);
      return;
    }
    if (this.formaPago === 'credito' && !this.datosCredito.inicial_monto) {
      this.evaluacion.set(null);
      return;
    }
    this.ventaService.evaluar(this.idSeparacion, this.armarPayload(true)).subscribe({
      next: (r) => {
        this.evaluacion.set(r);
        this.errorEvaluacion.set(null);
      },
      error: (err) => {
        this.evaluacion.set(null);
        const detalle = err?.error?.detail;
        this.errorEvaluacion.set(typeof detalle === 'string' ? detalle : null);
      },
    });
  }

  get requiereAutorizacion(): boolean {
    return !!this.evaluacion()?.requiere_autorizacion;
  }

  // ---- Compradores adicionales ----

  agregarComprador(c: Cliente, rol: RolExtra = 'copropietario'): void {
    if (c.id === this.separacion()?.id_cliente) {
      this.toastService.error('Ese cliente ya es el comprador titular');
      return;
    }
    if (this.extras().some((e) => e.cliente.id === c.id)) {
      this.toastService.error('Ese cliente ya está agregado');
      return;
    }
    if (this.extras().length >= this.MAX_EXTRAS) {
      this.toastService.error('Una venta admite como máximo 4 compradores');
      return;
    }
    this.extras.update((lista) => [...lista, { cliente: c, rol }]);
    this.agregando.set(false);
  }

  quitarComprador(idCliente: number): void {
    this.extras.update((lista) => lista.filter((e) => e.cliente.id !== idCliente));
  }

  cambiarRol(idCliente: number, rol: RolExtra): void {
    this.extras.update((lista) => lista.map((e) => (e.cliente.id === idCliente ? { ...e, rol } : e)));
  }

  irACrearCliente(texto: string): void {
    this.guardarBorrador();
    const esNumero = /^\d{6,}$/.test(texto);
    this.router.navigate(['/dashboard/clientes/nuevo'], {
      queryParams: {
        ...(esNumero ? { documento: texto } : {}),
        returnTo: `/dashboard/separaciones/${this.idSeparacion}/iniciar-venta`,
      },
    });
  }

  usarConyuge(): void {
    const sep = this.separacion();
    if (!sep) return;
    this.creandoConyuge.set(true);
    this.clienteService.conyugeComoCliente(sep.id_cliente).subscribe({
      next: (c) => {
        this.creandoConyuge.set(false);
        this.agregarComprador(c, 'conyuge');
      },
      error: (err) => {
        this.creandoConyuge.set(false);
        this.toastService.error(err?.error?.detail ?? 'No se pudo cargar al cónyuge');
      },
    });
  }

  // ---- Pagos previos (contado) ----

  agregarFilaPago(): void {
    this.pagosPrevios.push({ monto: null, fecha: '' });
  }

  quitarFilaPago(index: number): void {
    this.pagosPrevios.splice(index, 1);
  }

  // ---- Guardar ----

  mensajeFaltante(): string | null {
    if (!this.precioTotal || this.precioTotal <= 0) return 'Indica el precio total de la venta';
    if (this.formaPago === 'credito') {
      const dc = this.datosCredito;
      if (!dc.inicial_monto || !dc.fecha_deposito || !dc.numero_operacion.trim()) {
        return 'Completa la inicial, la fecha del depósito y el N° de operación del crédito';
      }
      if (!dc.plazo_meses || dc.plazo_meses < 1) return 'Indica el plazo en meses';
    }
    return null;
  }

  guardar(): void {
    const faltante = this.mensajeFaltante();
    if (faltante) {
      this.error.set(faltante);
      return;
    }
    if (!this.separacion()) return;

    this.error.set(null);
    this.guardando.set(true);

    // Se evalúa de nuevo en el servidor para no depender de una vista previa desactualizada
    this.ventaService.evaluar(this.idSeparacion, this.armarPayload(false)).subscribe({
      next: (ev) => (ev.requiere_autorizacion ? this.pedirAutorizacion() : this.crear()),
      error: (err) => this.fallo(err, 'No se pudo validar las condiciones'),
    });
  }

  private crear(): void {
    this.ventaService.crearDesdeSeparacion(this.idSeparacion, this.armarPayload(false)).subscribe({
      next: (venta) => {
        this.guardando.set(false);
        this.toastService.exito('Venta iniciada correctamente');
        this.router.navigate(['/dashboard/contratos/venta', venta.id]);
      },
      error: (err) => this.fallo(err, 'No se pudo iniciar la venta'),
    });
  }

  private pedirAutorizacion(): void {
    this.ventaService.solicitarAutorizacion(this.idSeparacion, this.armarPayload(false)).subscribe({
      next: () => {
        this.guardando.set(false);
        this.toastService.exito('Solicitud enviada a gerencia. Te avisaremos cuando la resuelva.');
        this.router.navigate(['/dashboard/separaciones', this.idSeparacion]);
      },
      error: (err) => this.fallo(err, 'No se pudo solicitar la autorización'),
    });
  }

  private fallo(err: any, porDefecto: string): void {
    this.guardando.set(false);
    const detalle = err?.error?.detail;
    const mensaje = typeof detalle === 'string' ? detalle : porDefecto;
    this.error.set(mensaje);
    this.toastService.error(mensaje);
  }

  cancelar(): void {
    this.router.navigate(['/dashboard/separaciones', this.idSeparacion]);
  }
}