import { CommonModule } from '@angular/common';
import { Component, OnDestroy, OnInit, computed, signal } from '@angular/core';
import { Subscription } from 'rxjs';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';

import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { SocketService } from '../../core/services/socket.service';
import { SeparacionService } from '../../core/services/separacion.service';
import { EstadoSeparacion, Proyecto, Separacion } from '../../core/models';

@Component({
  selector: 'app-separaciones-list',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './separaciones-list.component.html',
  styleUrl: './separaciones-list.component.css',
})
export class SeparacionesListComponent implements OnInit, OnDestroy {
  proyectos = signal<Proyecto[]>([]);
  separaciones = signal<Separacion[]>([]);
  cargando = signal(false);
    private suscripcionSocket?: Subscription;

  // ---- Filtro por ejecutivo (quién generó la separación) ----
  ejecutivoFiltro = signal<number | 'todos'>('todos');

  /** KPI: cuántas separaciones generó cada ejecutivo (mayor a menor) */
  ejecutivosKpi = computed(() => {
    const mapa = new Map<number, { id: number; nombre: string; total: number }>();
    for (const s of this.separaciones()) {
      const e = mapa.get(s.id_ejecutivo) ?? { id: s.id_ejecutivo, nombre: s.ejecutivo_nombre || 'Sin nombre', total: 0 };
      e.total++;
      mapa.set(s.id_ejecutivo, e);
    }
    return [...mapa.values()].sort((a, b) => b.total - a.total);
  });

  separacionesVista = computed(() => {
    const ej = this.ejecutivoFiltro();
    return ej === 'todos' ? this.separaciones() : this.separaciones().filter((s) => s.id_ejecutivo === ej);
  });

  idProyectoSeleccionado: number | null = null;
  filtroEstado: 'todos' | EstadoSeparacion = 'todos';

  readonly estados: { valor: EstadoSeparacion; etiqueta: string }[] = [
    { valor: 'pendiente_caja', etiqueta: 'Pendiente Caja' },
    { valor: 'pendiente_facturacion', etiqueta: 'Pendiente Facturación' },
    { valor: 'vigente', etiqueta: 'Vigente' },
    { valor: 'vencida', etiqueta: 'Vencida' },
    { valor: 'convertida', etiqueta: 'Convertida' },
    { valor: 'devolucion_pendiente', etiqueta: 'Devolución pendiente' },
    { valor: 'devuelta', etiqueta: 'Devuelta' },
    { valor: 'rechazada', etiqueta: 'Rechazada' },
  ];

  constructor(
    private api: ApiService,
    public auth: AuthService,
    private socket: SocketService,
    private separacionService: SeparacionService,
    private router: Router
  ) {}

  ngOnInit(): void {
    this.api.get<Proyecto[]>('/proyectos').subscribe((proyectos) => {
      this.proyectos.set(proyectos);
      if (proyectos.length > 0) {
        this.idProyectoSeleccionado = proyectos[0].id;
        this.cargarSeparaciones();
      }
    });

    this.socket.conectar();
    this.suscripcionSocket = this.socket.onEvento.subscribe((evento) => {
      if (evento.evento === 'separacion:actualizada') {
        const data = evento.data as { id_proyecto?: number };
        if (data?.id_proyecto === this.idProyectoSeleccionado) {
          this.cargarSeparaciones();
        }
      }
    });
  }

  ngOnDestroy(): void {
    this.suscripcionSocket?.unsubscribe();
    this.socket.desconectar();
  }

  cambiarProyecto(): void {
    this.cargarSeparaciones();
  }

  cambiarFiltro(): void {
    this.cargarSeparaciones();
  }

  /** Vuelve el filtro de estado a "Todos" y recarga. */
  limpiarFiltros(): void {
    this.ejecutivoFiltro.set('todos');
    this.filtroEstado = 'todos';
    this.cargarSeparaciones();
  }

  cargarSeparaciones(): void {
    if (!this.idProyectoSeleccionado) return;
    this.cargando.set(true);
    const estado = this.filtroEstado === 'todos' ? undefined : this.filtroEstado;
    this.separacionService.listar(this.idProyectoSeleccionado, estado).subscribe({
      next: (res) => {
        this.separaciones.set(res);
        this.cargando.set(false);
      },
      error: () => this.cargando.set(false),
    });
  }

  irAProformaRapida(): void {
    this.router.navigate(['/dashboard/separaciones/proformas'], {
      queryParams: { id_proyecto: this.idProyectoSeleccionado },
    });
  }

  irANueva(): void {
    this.router.navigate(['/dashboard/separaciones/nueva'], {
      queryParams: { id_proyecto: this.idProyectoSeleccionado },
    });
  }

  irADetalle(sep: Separacion): void {
    this.router.navigate(['/dashboard/separaciones', sep.id]);
  }

  etiquetaEstado(estado: EstadoSeparacion): string {
    return this.estados.find((e) => e.valor === estado)?.etiqueta ?? estado;
  }
}