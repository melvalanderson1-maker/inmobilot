import { CommonModule } from '@angular/common';
import { Component, ElementRef, HostListener, OnDestroy, OnInit, ViewChild, computed, signal } from '@angular/core';
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

  // ---- Búsqueda y orden ----
  busqueda = signal('');
  orden = signal<{ campo: 'lote' | 'cliente' | 'importe' | 'vencimiento' | 'estado'; dir: 'asc' | 'desc' } | null>(null);

  @ViewChild('buscador') buscador?: ElementRef<HTMLInputElement>;

  /** Quita tildes y mayúsculas para buscar sin complicaciones */
  private normalizar(t: unknown): string {
    return String(t ?? '')
      .normalize('NFD')
      .replace(/[\u0300-\u036f]/g, '')
      .toLowerCase()
      .trim();
  }

  separacionesVista = computed(() => {
    const ej = this.ejecutivoFiltro();
    const tokens = this.normalizar(this.busqueda()).split(/\s+/).filter(Boolean);
    let lista = this.separaciones().filter((s) => ej === 'todos' || s.id_ejecutivo === ej);

    if (tokens.length) {
      lista = lista.filter((s) => {
        const base = this.normalizar(
          [
            s.lote?.codigo,
            this.nombreCliente(s),
            this.docCliente(s),
            s.ejecutivo_nombre,
            this.etiquetaEstado(s.estado),
            s.importe,
            s.fecha_vencimiento,
            s.motivo_rechazo,
          ].join(' ')
        );
        return tokens.every((t) => base.includes(t));
      });
    }

    const o = this.orden();
    if (o) {
      const dir = o.dir === 'asc' ? 1 : -1;
      const valor = (s: Separacion): string | number => {
        switch (o.campo) {
          case 'lote': return this.normalizar(s.lote?.codigo);
          case 'cliente': return this.normalizar(this.nombreCliente(s));
          case 'importe': return Number(s.importe);
          case 'vencimiento': return String(s.fecha_vencimiento);
          default: return this.normalizar(this.etiquetaEstado(s.estado));
        }
      };
      lista = [...lista].sort((a, b) => {
        const x = valor(a);
        const y = valor(b);
        const r = typeof x === 'number' && typeof y === 'number' ? x - y : String(x).localeCompare(String(y), 'es', { numeric: true });
        return r * dir;
      });
    }
    return lista;
  });

  get hayFiltros(): boolean {
    return !!this.busqueda().trim() || this.ejecutivoFiltro() !== 'todos' || this.filtroEstado !== 'todos';
  }

  /** Atajo: la tecla "/" lleva el cursor al buscador */
  @HostListener('document:keydown', ['$event'])
  atajos(e: KeyboardEvent): void {
    const t = e.target as HTMLElement | null;
    const escribiendo = !!t && (['INPUT', 'TEXTAREA', 'SELECT'].includes(t.tagName) || t.isContentEditable);
    if (e.key === '/' && !escribiendo) {
      e.preventDefault();
      this.buscador?.nativeElement.focus();
    }
  }

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
    { valor: 'anulada', etiqueta: 'Anulada' },
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
        if (Number(data?.id_proyecto) === Number(this.idProyectoSeleccionado)) this.cargarSeparaciones(true);
      }
      // Respaldo: la notificación privada llega aunque tu token no tenga el proyecto en la sala
      if (evento.evento === 'notificacion:nueva') {
        const n = evento.data as { tipo?: string };
        if (String(n?.tipo ?? '').startsWith('separacion_')) this.cargarSeparaciones(true);
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

  /** Limpia búsqueda, ejecutivo y estado, y recarga. */
  limpiarFiltros(): void {
    this.busqueda.set('');
    this.ejecutivoFiltro.set('todos');
    this.filtroEstado = 'todos';
    this.cargarSeparaciones();
  }

  limpiarBusqueda(): void {
    this.busqueda.set('');
    this.buscador?.nativeElement.focus();
  }

  cargarSeparaciones(silencioso = false): void {
    if (!this.idProyectoSeleccionado) return;
    if (!silencioso) this.cargando.set(true);
    const estado = this.filtroEstado === 'todos' ? undefined : this.filtroEstado;
    this.separacionService.listar(Number(this.idProyectoSeleccionado), estado).subscribe({
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

  nombreCliente(sep: Separacion): string {
    return sep.cliente ? `${sep.cliente.nombres} ${sep.cliente.apellidos}`.trim() : '';
  }

  /** Si tu modelo usa otro nombre para el documento, cámbialo aquí */
  docCliente(sep: Separacion): string {
    return String((sep.cliente as any)?.numero_documento ?? '');
  }

  inicial(sep: Separacion): string {
    return (sep.cliente?.nombres ?? '?').trim().charAt(0).toUpperCase() || '?';
  }

  ordenarPor(campo: 'lote' | 'cliente' | 'importe' | 'vencimiento' | 'estado'): void {
    const o = this.orden();
    if (!o || o.campo !== campo) this.orden.set({ campo, dir: 'asc' });
    else if (o.dir === 'asc') this.orden.set({ campo, dir: 'desc' });
    else this.orden.set(null);
  }

  dirOrden(campo: string): string {
    const o = this.orden();
    return o && o.campo === campo ? o.dir : '';
  }

  ariaSort(campo: string): 'ascending' | 'descending' | 'none' {
    const d = this.dirOrden(campo);
    return d === 'asc' ? 'ascending' : d === 'desc' ? 'descending' : 'none';
  }

  /** Aviso de vencimiento solo para separaciones vigentes */
  vencimientoInfo(sep: Separacion): { texto: string; clase: string } | null {
    if (sep.estado !== 'vigente') return null;
    const [y, m, d] = String(sep.fecha_vencimiento).slice(0, 10).split('-').map(Number);
    if (!y || !m || !d) return null;
    const hoy = new Date();
    hoy.setHours(0, 0, 0, 0);
    const dias = Math.round((new Date(y, m - 1, d).getTime() - hoy.getTime()) / 86400000);
    if (dias < 0) return { texto: `Venció hace ${-dias} d`, clase: 'venc-mal' };
    if (dias === 0) return { texto: 'Vence hoy', clase: 'venc-alerta' };
    if (dias <= 3) return { texto: `Vence en ${dias} d`, clase: 'venc-alerta' };
    return { texto: `Faltan ${dias} d`, clase: 'venc-ok' };
  }
}