import { CommonModule } from '@angular/common';
import { Component, HostListener, OnDestroy, OnInit, computed, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute } from '@angular/router';

import { ApiService } from '../../core/services/api.service';
import { SocketService } from '../../core/services/socket.service';
import { LotePublico, Proyecto } from '../../core/models';

import { TenantService } from '../../core/services/tenant.service';

type FiltroEstado = 'todos' | 'libre' | 'separado' | 'vendido' | 'bloqueado';
type OrdenPrecio = 'relevancia' | 'menor' | 'mayor';
@Component({
  selector: 'app-catalogo',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './catalogo.component.html',
  styleUrl: './catalogo.component.css',
})
export class CatalogoComponent implements OnInit, OnDestroy {
  lotes = signal<LotePublico[]>([]);
  cargando = signal(true);

  // Header flotante al hacer scroll (activa la clase .gv-header--flotante)
  headerFlotante = signal(false);

  // AJUSTA: tipado como `any` a propósito para no depender de campos
  // que quizás tu interfaz Proyecto no tenga (nombre, ubicacion, etc.)
  proyecto = signal<any | null>(null);

  modalAbierto = signal(false);
  loteSeleccionado = signal<LotePublico | null>(null);
  enviandoLead = signal(false);
  leadEnviado = signal(false);

  // Mascota decorativa (tucán de la Selva Central)
  mascotaVisible = signal(true);
  nombre = '';
  telefono = '';
  correo = '';

  skeletonItems = Array.from({ length: 8 });

  // Filtro avanzado: estado (selección única), rango de precio y orden
  estadosDisponibles: { valor: FiltroEstado; etiqueta: string }[] = [
    { valor: 'todos', etiqueta: 'Todos los lotes' },
    { valor: 'libre', etiqueta: 'Disponible' },
    { valor: 'separado', etiqueta: 'Separado' },
    { valor: 'vendido', etiqueta: 'Vendido' },
    { valor: 'bloqueado', etiqueta: 'Bloqueado' },
  ];

  filtroEstado = signal<FiltroEstado>('todos');
  ordenPrecio = signal<OrdenPrecio>('relevancia');
  precioMin = signal<number | null>(null);
  precioMax = signal<number | null>(null);

  // Resaltado del card al llegar desde la maqueta
  loteResaltado = signal<number | null>(null);

  // Drawer lateral del mapa/maqueta
  mapaAbierto = signal(false);

  abrirMapa(): void {
    this.mapaAbierto.set(true);
  }

  cerrarMapa(): void {
    this.mapaAbierto.set(false);
  }

  // AJUSTA: posición (%) de cada lote sobre la imagen de la maqueta.
  // Clave = código del lote (lote.codigo). Mide sobre tu imagen real
  // (0% = borde izquierdo/superior, 100% = borde derecho/inferior).
  coordenadasMaqueta: Record<string, { x: number; y: number }> = {
    B16: { x: 66.7, y: 78 },
    B17: { x: 67, y: 72.7 },
    B18: { x: 65.6, y: 59.2 },
    B19: { x: 67, y: 52.2 },
    B20: { x: 70.2, y: 48.4 },
    B21: { x: 73.6, y: 43.2 },
    B22: { x: 80.4, y: 38.4 },
    B23: { x: 76.9, y: 31.6 },
  };
  // Carrusel: índice de imagen actual por lote
  indiceImagenPorLote = signal<Record<number, number>>({});
  private intervaloCarrusel: ReturnType<typeof setInterval> | null = null;


  lotesFiltrados = computed(() => {
    const estado = this.filtroEstado();
    const min = this.precioMin();
    const max = this.precioMax();
    const orden = this.ordenPrecio();

    let resultado = estado === 'todos' ? this.lotes() : this.lotes().filter((l) => l.estado === estado);

    if (min !== null) {
      resultado = resultado.filter((l) => !l.precio_total_contado || l.precio_total_contado >= min);
    }
    if (max !== null) {
      resultado = resultado.filter((l) => !l.precio_total_contado || l.precio_total_contado <= max);
    }

    if (orden === 'menor') {
      resultado = [...resultado].sort(
        (a, b) => (a.precio_total_contado ?? Infinity) - (b.precio_total_contado ?? Infinity)
      );
    } else if (orden === 'mayor') {
      resultado = [...resultado].sort(
        (a, b) => (b.precio_total_contado ?? -Infinity) - (a.precio_total_contado ?? -Infinity)
      );
    }

    return resultado;
  });

  lotesConCoordenadas = computed(() =>
    this.lotes().filter((l) => this.coordenadasMaqueta[l.codigo])
  );

  posicionLote(lote: LotePublico): { x: number; y: number } {
    return this.coordenadasMaqueta[lote.codigo] ?? { x: 50, y: 50 };
  }

  cambiarFiltroEstado(valor: FiltroEstado): void {
    this.filtroEstado.set(valor);
  }

  estadoActivo(valor: FiltroEstado): boolean {
    return this.filtroEstado() === valor;
  }

  cambiarOrden(valor: OrdenPrecio): void {
    this.ordenPrecio.set(valor);
  }

  actualizarPrecioMin(valor: string): void {
    this.precioMin.set(valor ? Number(valor) : null);
  }

  actualizarPrecioMax(valor: string): void {
    this.precioMax.set(valor ? Number(valor) : null);
  }

  limpiarFiltros(): void {
    this.filtroEstado.set('todos');
    this.ordenPrecio.set('relevancia');
    this.precioMin.set(null);
    this.precioMax.set(null);
  }

  irALote(lote: LotePublico): void {
    this.cerrarMapa();
    setTimeout(() => {
      const el = document.getElementById('lote-' + lote.id);
      if (!el) return;
      el.scrollIntoView({ behavior: 'smooth', block: 'center' });
      this.loteResaltado.set(lote.id);
      setTimeout(() => this.loteResaltado.set(null), 2200);
    }, 350);
  }
  private empresaSlug = '';
  private proyectoSlug = 'oro-verde';
  private idProyecto: number | null = null;

  constructor(
    private api: ApiService,
    private route: ActivatedRoute,
    private socket: SocketService,
    public tenant: TenantService
  ) {}

  @HostListener('window:scroll')
  onWindowScroll(): void {
    const y = window.scrollY;
    if (y > 60) {
      this.headerFlotante.set(true);
    } else if (y < 20) {
      this.headerFlotante.set(false);
    }
  }

  ngOnInit(): void {
    this.empresaSlug = this.route.snapshot.paramMap.get('empresaSlug') ?? this.tenant.config()?.slug ?? '';
    this.proyectoSlug = this.route.snapshot.paramMap.get('proyectoSlug') ?? this.proyectoSlug;
    this.cargarProyectoYLotes();
    this.iniciarCarruselAutomatico();
  }

  private iniciarCarruselAutomatico(): void {
    this.intervaloCarrusel = setInterval(() => {
      const conVariasImagenes = this.lotes().filter((l) => this.imagenesUrls(l).length > 1);
      if (conVariasImagenes.length === 0) return;

      this.indiceImagenPorLote.update((mapa) => {
        const nuevo = { ...mapa };
        for (const lote of conVariasImagenes) {
          const total = this.imagenesUrls(lote).length;
          const actual = nuevo[lote.id] ?? 0;
          nuevo[lote.id] = (actual + 1) % total;
        }
        return nuevo;
      });
    }, 4000);
  }

  private cargarProyectoYLotes(): void {
    this.cargando.set(true);
    this.api.get<Proyecto[]>(`/public/proyectos/${this.empresaSlug}`).subscribe({
      next: (proyectos) => {
        const proyecto = proyectos.find((p) => p.slug === this.proyectoSlug);
        this.idProyecto = proyecto?.id ?? null;
        this.proyecto.set(proyecto ?? null);
        this.cargarLotes();

        if (this.idProyecto) {
          this.socket.conectarPublico(this.idProyecto);
          this.socket.onEvento.subscribe((evento) => {
            if (evento.evento === 'lote:cambio_estado') {
              const loteActualizado = evento.data as LotePublico;
              this.lotes.update((actuales) =>
                actuales.map((l) =>
                  l.id === loteActualizado.id ? { ...l, estado: loteActualizado.estado } : l
                )
              );
            }
            if (evento.evento === 'lote:nuevo') {
              const loteNuevo = evento.data as LotePublico;
              this.lotes.update((actuales) => {
                const yaExiste = actuales.some((l) => l.id === loteNuevo.id);
                return yaExiste ? actuales : [...actuales, loteNuevo];
              });
            }
            if (evento.evento === 'lote:actualizado') {
              const loteActualizado = evento.data as LotePublico;
              this.lotes.update((actuales) =>
                actuales.map((l) => (l.id === loteActualizado.id ? { ...l, ...loteActualizado } : l))
              );
              this.indiceImagenPorLote.update((mapa) => ({ ...mapa, [loteActualizado.id]: 0 }));
            }
          });
        }
      },
      error: () => this.cargando.set(false),
    });
  }

  cargarLotes(): void {
    this.api
      .get<LotePublico[]>(`/public/proyectos/${this.empresaSlug}/${this.proyectoSlug}/lotes`)
      .subscribe({
        next: (lotes) => {
          this.lotes.set(lotes);
          this.cargando.set(false);
        },
        error: () => this.cargando.set(false),
      });
  }



  verLote(lote: LotePublico): void {
    this.loteSeleccionado.set(lote);
    this.leadEnviado.set(false);
    this.modalAbierto.set(true);
  }

  cerrarModal(): void {
    this.modalAbierto.set(false);
    this.nombre = '';
    this.telefono = '';
    this.correo = '';
  }

  cerrarMascota(): void {
    this.mascotaVisible.set(false);
  }

  enviarLead(): void {
    const lote = this.loteSeleccionado();
    if (!lote || !this.nombre || !this.telefono) return;

    this.enviandoLead.set(true);
    this.api
      .post('/public/leads', {
        id_proyecto: this.idProyecto,
        id_lote: lote.id,
        nombre: this.nombre,
        telefono: this.telefono,
        correo: this.correo || null,
        origen: 'web',
      })
      .subscribe({
        next: () => {
          this.enviandoLead.set(false);
          this.leadEnviado.set(true);
        },
        error: () => {
          this.enviandoLead.set(false);
        },
      });
  }

  claseEstado(estado: string): string {
    return `badge badge-${estado}`;
  }

  nombreProyecto(): string {
    const p = this.proyecto();
    if (p?.nombre) return p.nombre;
    return this.proyectoSlug
      .split('-')
      .map((palabra) => palabra.charAt(0).toUpperCase() + palabra.slice(1))
      .join(' ');
  }

  ubicacionProyecto(): string {
    return this.proyecto()?.ubicacion ?? 'Mazamari, Selva Central';
  }

  lotesDisponibles(): number {
    return this.lotes().filter((l) => l.estado === 'libre').length;
  }

  precioDesde(): number | null {
    const precios = this.lotes()
      .filter((l) => l.estado === 'libre' && l.precio_total_base)
      .map((l) => l.precio_total_base as number);
    return precios.length ? Math.min(...precios) : null;
  }

  areaDesde(): number | null {
    const areas = this.lotes()
      .filter((l) => l.estado === 'libre' && l.area_m2)
      .map((l) => l.area_m2 as number);
    return areas.length ? Math.min(...areas) : null;
  }

  imagenPrincipal(lote: LotePublico): string | null {
    if (!lote.imagenes || lote.imagenes.length === 0) {
      return null;
    }

    const url = lote.imagenes[0].url;

    // Si ya viene como URL completa, la usamos directamente
    if (url.startsWith('http://') || url.startsWith('https://')) {
      return url;
    }

    // En desarrollo, las imágenes están en FastAPI
    return `http://localhost:8000${url}`;
  }



    imagenesUrls(lote: LotePublico): string[] {
    if (!lote.imagenes || lote.imagenes.length === 0) return [];
    return lote.imagenes.map((img) => {
      if (img.url.startsWith('http://') || img.url.startsWith('https://')) return img.url;
      return `http://localhost:8000${img.url}`;
    });
  }

  indiceActual(lote: LotePublico): number {
    return this.indiceImagenPorLote()[lote.id] ?? 0;
  }

  imagenActual(lote: LotePublico): string | null {
    const urls = this.imagenesUrls(lote);
    if (urls.length === 0) return null;
    const idx = this.indiceActual(lote);
    return urls[idx] ?? urls[0];
  }

  siguienteImagen(lote: LotePublico, event: Event): void {
    event.stopPropagation();
    const urls = this.imagenesUrls(lote);
    if (urls.length <= 1) return;
    const actual = this.indiceActual(lote);
    const siguiente = (actual + 1) % urls.length;
    this.indiceImagenPorLote.update((mapa) => ({ ...mapa, [lote.id]: siguiente }));
  }

  anteriorImagen(lote: LotePublico, event: Event): void {
    event.stopPropagation();
    const urls = this.imagenesUrls(lote);
    if (urls.length <= 1) return;
    const actual = this.indiceActual(lote);
    const anterior = (actual - 1 + urls.length) % urls.length;
    this.indiceImagenPorLote.update((mapa) => ({ ...mapa, [lote.id]: anterior }));
  }

  irAImagen(lote: LotePublico, index: number, event: Event): void {
    event.stopPropagation();
    this.indiceImagenPorLote.update((mapa) => ({ ...mapa, [lote.id]: index }));
  }

  ngOnDestroy(): void {
    this.socket.desconectar();
    if (this.intervaloCarrusel) {
      clearInterval(this.intervaloCarrusel);
    }
  }
}