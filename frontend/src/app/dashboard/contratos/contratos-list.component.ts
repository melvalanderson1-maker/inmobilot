import { CommonModule } from '@angular/common';
import { Component, HostListener, OnDestroy, OnInit, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { environment } from '../../../environments/environment';
import { ApiService } from '../../core/services/api.service';
import { ContratoService } from '../../core/services/contrato.service';
import { SocketService } from '../../core/services/socket.service';
import {
  Proyecto,
  Lote,
  Contrato,
  ContratoCreate,
  ContratoClienteInfo,
  CronogramaCuota,
  Pago,
  PagoCreate,
  FormaPago,
} from '../../core/models';

interface ResumenContrato {
  totalPagado: number;
  saldoPendiente: number;
  cuotasPagadas: number;
  cuotasPendientes: number;
  cuotasVencidas: number;
  interesTotal: number;
  proximaFecha: string | null;
}

@Component({
  selector: 'app-contratos-list',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './contratos-list.component.html',
  styleUrl: './contratos-list.component.css',
})
export class ContratosListComponent implements OnInit, OnDestroy {
  proyectos = signal<Proyecto[]>([]);
  idProyectoSeleccionado: number | null = null;

  contratos = signal<Contrato[]>([]);
  lotesLibres = signal<Lote[]>([]);
  cargando = signal(false);

  // ---- Drawer de detalle ----
  drawerAbierto = signal(false);
  contratoDrawer = signal<Contrato | null>(null);
  cronogramaPorContrato = signal<Partial<Record<number, CronogramaCuota[]>>>({});
  pagosPorContrato = signal<Partial<Record<number, Pago[]>>>({});
  cargandoCronograma = signal<number | null>(null);
  detalleMensual = signal<Record<number, boolean>>({});

  modalComprobanteAbierto = signal(false);
  comprobanteUrlActual = signal<string | null>(null);

  // ---- Modal nuevo contrato ----
  modalAbierto = signal(false);
  guardando = signal(false);
  error = signal<string | null>(null);

  numeroContrato = '';
  idLote: number | null = null;
  fechaContrato = new Date().toISOString().slice(0, 10);
  formaPago: FormaPago = 'contado';
  frecuenciaCuota: 'mensual' | 'anual' = 'mensual';
  precioTotal: number | null = null;
  inicialAbonado = 0;
  fechaAbono = '';
  numeroCuotas: number | null = null;
  tieneInteres = false;
  tem: number | null = null;
  fechaInicioInteres = '';
  tipoContrato = '';
  observaciones = '';

  tipoDocumento = 'DNI';
  numeroDocumento = '';
  nombresCliente = '';
  apellidosCliente = '';
  correoCliente = '';
  telefonoCliente = '';
  direccionCliente = '';

  // ---- Modal registrar pago ----
  modalPagoAbierto = signal(false);
  guardandoPago = signal(false);
  errorPago = signal<string | null>(null);
  contratoPagoId: number | null = null;
  cuotaSeleccionada: CronogramaCuota | null = null;
  montoPago: number | null = null;
  fechaPago = new Date().toISOString().slice(0, 10);
  metodoPago = 'efectivo';
  numeroOperacion = '';
  observacionPago = '';
  archivoComprobante: File | null = null;

  get saldoFinanciado(): number {
    const precio = this.precioTotal ?? 0;
    const inicial = this.inicialAbonado ?? 0;
    return Math.max(precio - inicial, 0);
  }

  get plazoTotalMeses(): number {
    const cuotas = this.numeroCuotas ?? 0;
    return this.frecuenciaCuota === 'anual' ? cuotas * 12 : cuotas;
  }

  constructor(
    private api: ApiService,
    private contratoService: ContratoService,
    private socket: SocketService
  ) {}

  ngOnInit(): void {
    this.api.get<Proyecto[]>('/proyectos').subscribe((proyectos) => {
      this.proyectos.set(proyectos);
      if (proyectos.length > 0) {
        this.idProyectoSeleccionado = proyectos[0].id;
        this.cambiarProyecto();
      }
    });

    this.socket.conectar();
    this.socket.onEvento.subscribe((evento) => {
      if (evento.evento === 'contrato:nuevo') {
        const contrato = evento.data as Contrato;
        if (contrato && contrato.id_proyecto === this.idProyectoSeleccionado) {
          this.cargarContratos();
          this.cargarLotesLibres();
        }
      }
      if (evento.evento === 'contrato:pago_registrado') {
        const idContrato = (evento.data as any)?.id_contrato;
        if (idContrato && this.contratoDrawer()?.id === idContrato) {
          this.cargarCronograma(idContrato);
        }
      }
    });
  }

  ngOnDestroy(): void {
    this.socket.desconectar();
  }

  cambiarProyecto(): void {
    if (!this.idProyectoSeleccionado) return;
    this.cargarContratos();
    this.cargarLotesLibres();
  }

  cargarContratos(): void {
    if (!this.idProyectoSeleccionado) return;
    this.cargando.set(true);
    this.contratoService.listar(this.idProyectoSeleccionado).subscribe({
      next: (res) => {
        this.contratos.set(res);
        this.cargando.set(false);
      },
      error: () => this.cargando.set(false),
    });
  }

  cargarLotesLibres(): void {
    if (!this.idProyectoSeleccionado) return;
    this.api.get<Lote[]>('/lotes', { id_proyecto: this.idProyectoSeleccionado }).subscribe((lotes) => {
      this.lotesLibres.set(lotes.filter((l) => l.estado === 'libre'));
    });
  }

  // ---- Drawer ----

  abrirDrawer(contrato: Contrato): void {
    this.contratoDrawer.set(contrato);
    this.drawerAbierto.set(true);
    if (!this.cronogramaPorContrato()[contrato.id]) {
      this.cargarCronograma(contrato.id);
    }
  }

  cerrarDrawer(): void {
    this.drawerAbierto.set(false);
  }

  cargarCronograma(idContrato: number): void {
    this.cargandoCronograma.set(idContrato);
    this.contratoService.cronograma(idContrato).subscribe({
      next: (cuotas) => {
        this.cronogramaPorContrato.update((actual) => ({ ...actual, [idContrato]: cuotas }));
        this.cargandoCronograma.set(null);
      },
      error: () => this.cargandoCronograma.set(null),
    });

    this.contratoService.listarPagos(idContrato).subscribe({
      next: (pagos) => {
        this.pagosPorContrato.update((actual) => ({ ...actual, [idContrato]: pagos }));
      },
    });
  }

  toggleDetalleMensual(idContrato: number): void {
    this.detalleMensual.update((actual) => ({ ...actual, [idContrato]: !actual[idContrato] }));
  }

  cuotasVisibles(contrato: Contrato): CronogramaCuota[] {
    const todas = this.cronogramaPorContrato()[contrato.id] ?? [];
    if (contrato.frecuencia_cuota === 'anual' && !this.detalleMensual()[contrato.id]) {
      return todas.filter((c) => c.requiere_pago);
    }
    return todas;
  }

  resumen(contrato: Contrato): ResumenContrato {
    const cuotas = (this.cronogramaPorContrato()[contrato.id] ?? []).filter((c) => c.requiere_pago);
    const pagos = this.pagosPorContrato()[contrato.id] ?? [];

    const totalPagado = pagos.reduce((acc, p) => acc + Number(p.monto), 0);
    const saldoPendiente = Math.max(Number(contrato.saldo_financiado) - totalPagado, 0);
    const cuotasPagadas = cuotas.filter((c) => c.estado === 'pagada').length;
    const cuotasPendientes = cuotas.filter((c) => c.estado === 'pendiente' || c.estado === 'parcial').length;
    const cuotasVencidas = cuotas.filter((c) => c.estado === 'vencida').length;
    const interesTotal = (this.cronogramaPorContrato()[contrato.id] ?? []).reduce(
      (acc, c) => acc + Number(c.interes_mensual ?? 0),
      0
    );
    const proxima = cuotas.find((c) => c.estado !== 'pagada');

    return {
      totalPagado,
      saldoPendiente,
      cuotasPagadas,
      cuotasPendientes,
      cuotasVencidas,
      interesTotal,
      proximaFecha: proxima ? proxima.fecha_pago_programada : null,
    };
  }

  urlCompleta(relativa?: string): string | null {
    return relativa ? environment.apiUrl + relativa : null;
  }

  esImagen(url: string): boolean {
    return /\.(jpg|jpeg|png)$/i.test(url);
  }

  abrirComprobante(relativa?: string): void {
    const url = this.urlCompleta(relativa);
    if (!url) return;
    this.comprobanteUrlActual.set(url);
    this.modalComprobanteAbierto.set(true);
  }

  clienteTitular(contrato: Contrato): ContratoClienteInfo | undefined {
    return contrato.clientes[0];
  }

  cerrarComprobante(): void {
    this.modalComprobanteAbierto.set(false);
    this.comprobanteUrlActual.set(null);
  }

  @HostListener('document:keydown.escape')
  onEscape(): void {
    if (this.modalComprobanteAbierto()) {
      this.cerrarComprobante();
      return;
    }
    if (this.modalPagoAbierto()) {
      this.cerrarModalPago();
      return;
    }
    if (this.modalAbierto()) {
      this.cerrarModal();
      return;
    }
    if (this.drawerAbierto()) {
      this.cerrarDrawer();
    }
  }

  // ---- Nuevo contrato ----

  abrirNuevoContrato(): void {
    this.numeroContrato = '';
    this.idLote = null;
    this.fechaContrato = new Date().toISOString().slice(0, 10);
    this.formaPago = 'contado';
    this.frecuenciaCuota = 'mensual';
    this.precioTotal = null;
    this.inicialAbonado = 0;
    this.fechaAbono = '';
    this.numeroCuotas = null;
    this.tieneInteres = false;
    this.tem = null;
    this.fechaInicioInteres = '';
    this.tipoContrato = '';
    this.observaciones = '';
    this.tipoDocumento = 'DNI';
    this.numeroDocumento = '';
    this.nombresCliente = '';
    this.apellidosCliente = '';
    this.correoCliente = '';
    this.telefonoCliente = '';
    this.direccionCliente = '';
    this.error.set(null);
    this.modalAbierto.set(true);
  }

  onLoteSeleccionado(): void {
    const lote = this.lotesLibres().find((l) => l.id === this.idLote);
    if (!lote) return;
    this.precioTotal =
      this.formaPago === 'contado'
        ? Number(lote.precio_total_contado ?? lote.precio_total_base ?? 0)
        : Number(lote.precio_total_financiado ?? lote.precio_total_base ?? 0);
  }

  onFormaPagoChange(): void {
    this.onLoteSeleccionado();
  }

  cerrarModal(): void {
    this.modalAbierto.set(false);
  }

  guardarContrato(): void {
    if (!this.idProyectoSeleccionado || !this.idLote || !this.numeroContrato || !this.precioTotal) {
      this.error.set('Completa lote, número de contrato y precio total');
      return;
    }
    if (!this.numeroDocumento || !this.nombresCliente || !this.apellidosCliente) {
      this.error.set('Completa los datos del cliente titular');
      return;
    }
    if (this.formaPago === 'credito' && (!this.numeroCuotas || this.numeroCuotas <= 0)) {
      this.error.set('Indica el número de cuotas para un crédito');
      return;
    }

    const payload: ContratoCreate = {
      numero_contrato: this.numeroContrato,
      id_lote: this.idLote,
      fecha_contrato: this.fechaContrato,
      precio_total: this.precioTotal,
      inicial_abonado: this.inicialAbonado || 0,
      fecha_abono: this.fechaAbono || undefined,
      tiene_interes: this.formaPago === 'credito' ? this.tieneInteres : false,
      forma_pago: this.formaPago,
      frecuencia_cuota: this.formaPago === 'credito' ? this.frecuenciaCuota : 'mensual',
      saldo_financiado: this.formaPago === 'credito' ? this.saldoFinanciado : 0,
      numero_cuotas: this.formaPago === 'credito' ? this.numeroCuotas! : 0,
      tem: this.tieneInteres ? this.tem ?? undefined : undefined,
      fecha_inicio_interes: this.tieneInteres ? this.fechaInicioInteres || undefined : undefined,
      tipo_contrato: this.tipoContrato || undefined,
      observaciones: this.observaciones || undefined,
      clientes: [
        {
          rol: 'titular',
          cliente_nuevo: {
            tipo_documento: this.tipoDocumento,
            numero_documento: this.numeroDocumento,
            nombres: this.nombresCliente,
            apellidos: this.apellidosCliente,
            correo: this.correoCliente || undefined,
            telefono: this.telefonoCliente || undefined,
            direccion: this.direccionCliente || undefined,
          },
        },
      ],
    };

    this.guardando.set(true);
    this.error.set(null);

    this.contratoService.crear(payload).subscribe({
      next: () => {
        this.guardando.set(false);
        this.modalAbierto.set(false);
        this.cargarContratos();
        this.cargarLotesLibres();
      },
      error: (err) => {
        this.guardando.set(false);
        this.error.set(err?.error?.detail ?? 'Error al crear el contrato');
      },
    });
  }

  // ---- Registrar pago ----

  abrirRegistrarPago(idContrato: number, cuota: CronogramaCuota): void {
    this.contratoPagoId = idContrato;
    this.cuotaSeleccionada = cuota;
    this.montoPago = Number(cuota.monto_cuota) - Number(cuota.monto_pagado ?? 0);
    this.fechaPago = new Date().toISOString().slice(0, 10);
    this.metodoPago = 'efectivo';
    this.numeroOperacion = '';
    this.observacionPago = '';
    this.archivoComprobante = null;
    this.errorPago.set(null);
    this.modalPagoAbierto.set(true);
  }

  cerrarModalPago(): void {
    this.modalPagoAbierto.set(false);
  }

  onArchivoSeleccionado(event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0] ?? null;
    if (!file) {
      this.archivoComprobante = null;
      return;
    }

    const tiposPermitidos = ['image/jpeg', 'image/png', 'application/pdf'];
    if (!tiposPermitidos.includes(file.type)) {
      this.errorPago.set('Solo se permiten archivos JPG, PNG o PDF');
      this.archivoComprobante = null;
      return;
    }
    if (file.size > 8 * 1024 * 1024) {
      this.errorPago.set('El archivo no debe superar los 8MB');
      this.archivoComprobante = null;
      return;
    }

    this.errorPago.set(null);
    this.archivoComprobante = file;
  }

  guardarPago(): void {
    if (!this.contratoPagoId || !this.cuotaSeleccionada || !this.montoPago || this.montoPago <= 0) {
      this.errorPago.set('Indica un monto válido');
      return;
    }
    if (!this.archivoComprobante) {
      this.errorPago.set('Debes adjuntar el comprobante de pago (imagen o PDF)');
      return;
    }

    this.guardandoPago.set(true);
    this.errorPago.set(null);

    const formData = new FormData();
    formData.append('archivo', this.archivoComprobante);

    this.contratoService.subirComprobante(formData).subscribe({
      next: (res) => {
        const payload: PagoCreate = {
          id_cuota: this.cuotaSeleccionada!.id,
          monto: this.montoPago!,
          fecha_pago: this.fechaPago,
          metodo_pago: this.metodoPago,
          numero_operacion: this.numeroOperacion || undefined,
          observacion: this.observacionPago || undefined,
          comprobante_url: res.url,
        };

        this.contratoService.registrarPago(this.contratoPagoId!, payload).subscribe({
          next: () => {
            this.guardandoPago.set(false);
            this.modalPagoAbierto.set(false);
            this.cargarCronograma(this.contratoPagoId!);
          },
          error: (err) => {
            this.guardandoPago.set(false);
            this.errorPago.set(err?.error?.detail ?? 'Error al registrar el pago');
          },
        });
      },
      error: (err) => {
        this.guardandoPago.set(false);
        this.errorPago.set(err?.error?.detail ?? 'Error al subir el comprobante');
      },
    });
  }
}