import { CommonModule } from '@angular/common';
import { Component, OnDestroy, OnInit, computed, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';

import { ApiService } from '../../core/services/api.service';
import { CobranzaService } from '../../core/services/cobranza.service';
import { SocketService } from '../../core/services/socket.service';
import { CobranzaFila, Proyecto } from '../../core/models';

type FiltroCobranza = 'todos' | 'vencidos' | 'al_dia' | 'cancelados';

@Component({
  selector: 'app-cobranza-list',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './cobranza-list.component.html',
  styleUrl: './cobranza-list.component.css',
})
export class CobranzaListComponent implements OnInit, OnDestroy {
  proyectos = signal<Proyecto[]>([]);
  idProyecto: number | null = null;
  filas = signal<CobranzaFila[]>([]);
  cargando = signal(false);
  filtro = signal<FiltroCobranza>('todos');
  busqueda = signal('');

  filtros: { valor: FiltroCobranza; etiqueta: string }[] = [
    { valor: 'todos', etiqueta: 'Todos' },
    { valor: 'vencidos', etiqueta: 'Con atraso' },
    { valor: 'al_dia', etiqueta: 'Al día' },
    { valor: 'cancelados', etiqueta: 'Cancelados' },
  ];

  filtradas = computed(() => {
    const filtro = this.filtro();
    const texto = this.busqueda().trim().toLowerCase();
    return this.filas().filter((f) => {
      if (filtro === 'vencidos' && f.cuotas_vencidas === 0) return false;
      if (filtro === 'al_dia' && (f.cuotas_vencidas > 0 || f.estado === 'cancelado')) return false;
      if (filtro === 'cancelados' && f.estado !== 'cancelado') return false;
      if (texto) {
        const base = `${f.numero_contrato} ${f.lote_codigo ?? ''} ${f.cliente_nombre} ${f.cliente_documento} ${f.cliente_telefono ?? ''}`.toLowerCase();
        if (!base.includes(texto)) return false;
      }
      return true;
    });
  });

  kpiPorCobrar = computed(() =>
    this.filas().filter((f) => f.estado !== 'cancelado').reduce((a, f) => a + Number(f.saldo_pendiente), 0)
  );
  kpiVencido = computed(() => this.filas().reduce((a, f) => a + Number(f.monto_vencido), 0));
  kpiConAtraso = computed(() => this.filas().filter((f) => f.cuotas_vencidas > 0).length);
  kpiActivos = computed(() => this.filas().filter((f) => f.estado !== 'cancelado').length);

  constructor(
    private api: ApiService,
    private cobranzaService: CobranzaService,
    private socket: SocketService,
    private router: Router
  ) {}

  ngOnInit(): void {
    this.api.get<Proyecto[]>('/proyectos').subscribe((proyectos) => {
      this.proyectos.set(proyectos);
      if (proyectos.length > 0) {
        this.idProyecto = proyectos[0].id;
        this.cargar();
      }
    });

    this.socket.conectar();
    this.socket.onEvento.subscribe((e) => {
      if (['contrato:nuevo', 'contrato:pago_registrado', 'venta:actualizada'].includes(e.evento)) {
        this.cargar(true);
      }
    });
  }

  ngOnDestroy(): void {
    this.socket.desconectar();
  }

  cargar(silencioso = false): void {
    if (!this.idProyecto) return;
    if (!silencioso) this.cargando.set(true);
    this.cobranzaService.resumen(this.idProyecto).subscribe({
      next: (res) => {
        this.filas.set(res);
        this.cargando.set(false);
      },
      error: () => this.cargando.set(false),
    });
  }

  abrirContrato(f: CobranzaFila): void {
    this.router.navigate(['/dashboard/contratos'], { queryParams: { abrir: f.id_contrato } });
  }

  waUrl(telefono?: string): string | null {
    const digitos = (telefono ?? '').replace(/\D/g, '');
    if (digitos.length === 9) return `https://wa.me/51${digitos}`;
    if (digitos.length >= 11) return `https://wa.me/${digitos}`;
    return null;
  }
}