import { CommonModule } from '@angular/common';
import { Component, HostListener, OnDestroy, OnInit, computed, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { SocketService } from '../../core/services/socket.service';
import { LoteService } from '../../core/services/lote.service';
import { EstadoLote, Lote, Manzana, Proyecto } from '../../core/models';

@Component({
  selector: 'app-lotes-list',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './lotes-list.component.html',
  styleUrl: './lotes-list.component.css',
})
export class LotesListComponent implements OnInit, OnDestroy {
  proyectos = signal<Proyecto[]>([]);
  manzanas = signal<Manzana[]>([]);
  lotes = signal<Lote[]>([]);
  cargando = signal(false);

  idProyectoSeleccionado: number | null = null;

  // ---- Formulario (crear o editar) ----
  formularioAbierto = signal(false);
  loteEditando = signal<Lote | null>(null);
  guardando = signal(false);
  error = signal<string | null>(null);

  form = {
    id_manzana: null as number | null,
    codigo: '',
    ubicacion_lote: '',
    perimetro: null as number | null,
    area_m2: null as number | null,
    precio_m2_base: null as number | null,
    precio_total_base: null as number | null,
    precio_m2_contado: null as number | null,
    precio_total_contado: null as number | null,
    inicial_financiado: null as number | null,
    monto_financiado: null as number | null,
    precio_total_financiado: null as number | null,
    partida_registral: '',
  };

  // ---- Filtros y KPIs ----
  filtroEstado = signal<'todos' | EstadoLote>('todos');
  filtroBusqueda = signal('');
  filtroPrecioMin = signal<number | null>(null);
  filtroPrecioMax = signal<number | null>(null);

  lotesFiltrados = computed(() => {
    const estado = this.filtroEstado();
    const busqueda = this.filtroBusqueda().trim().toLowerCase();
    const min = this.filtroPrecioMin();
    const max = this.filtroPrecioMax();

    return this.lotes().filter((l) => {
      if (estado !== 'todos' && l.estado !== estado) return false;
      if (busqueda) {
        const texto = `${l.codigo} ${l.ubicacion_lote ?? ''}`.toLowerCase();
        if (!texto.includes(busqueda)) return false;
      }
      const precio = l.precio_total_contado ?? l.precio_total_base ?? 0;
      if (min !== null && precio < min) return false;
      if (max !== null && precio > max) return false;
      return true;
    });
  });

  kpiTotal = computed(() => this.lotes().length);
  kpiDisponibles = computed(() => this.lotes().filter((l) => l.estado === 'libre').length);
  kpiSeparados = computed(() => this.lotes().filter((l) => l.estado === 'separado').length);
  kpiVendidos = computed(() => this.lotes().filter((l) => l.estado === 'vendido').length);
  kpiValorInventario = computed(() =>
    this.lotes().reduce((acc, l) => acc + Number(l.precio_total_contado ?? l.precio_total_base ?? 0), 0)
  );

  limpiarFiltros(): void {
    this.filtroEstado.set('todos');
    this.filtroBusqueda.set('');
    this.filtroPrecioMin.set(null);
    this.filtroPrecioMax.set(null);
  }

  // ---- Imágenes ----
  archivosNuevos: File[] = [];
  previsualizaciones: string[] = [];
  subiendoImagenes = signal(false);

  // ---- Visor de imagen ----
  modalImagenAbierto = signal(false);
  imagenUrlActual = signal<string | null>(null);

  constructor(
    private api: ApiService,
    public auth: AuthService,
    private socket: SocketService,
    private loteService: LoteService
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
      if (
        evento.evento === 'lote:nuevo' ||
        evento.evento === 'lote:cambio_estado' ||
        evento.evento === 'lote:actualizado'
      ) {
        const lote = evento.data as Lote;
        if (lote && (lote as any).id_proyecto === this.idProyectoSeleccionado) {
          this.cargarLotes();
        }
      }
      if (evento.evento === 'usuario:proyectos_actualizados') {
        this.recargarProyectosAsignados();
      }
    });
  }

  private recargarProyectosAsignados(): void {
    this.api.get<Proyecto[]>('/proyectos').subscribe((proyectos) => {
      this.proyectos.set(proyectos);
      const sigueSiendoValido = proyectos.some((p) => p.id === this.idProyectoSeleccionado);
      if (!sigueSiendoValido) {
        this.idProyectoSeleccionado = proyectos.length > 0 ? proyectos[0].id : null;
        this.cambiarProyecto();
      }
    });
  }

  ngOnDestroy(): void {
    this.socket.desconectar();
  }

  cambiarProyecto(): void {
    if (!this.idProyectoSeleccionado) return;
    this.cargarManzanas();
    this.cargarLotes();
  }

  cargarManzanas(): void {
    this.api
      .get<Manzana[]>(`/proyectos/${this.idProyectoSeleccionado}/manzanas`)
      .subscribe((res) => this.manzanas.set(res));
  }

  cargarLotes(): void {
    this.cargando.set(true);
    this.api
      .get<Lote[]>('/lotes', { id_proyecto: this.idProyectoSeleccionado })
      .subscribe({
        next: (res) => {
          this.lotes.set(res);
          this.cargando.set(false);
        },
        error: () => this.cargando.set(false),
      });
  }

  // ---- Abrir formulario ----

  abrirNuevo(): void {
    this.loteEditando.set(null);
    this.form = {
      id_manzana: null,
      codigo: '',
      ubicacion_lote: '',
      perimetro: null,
      area_m2: null,
      precio_m2_base: null,
      precio_total_base: null,
      precio_m2_contado: null,
      precio_total_contado: null,
      inicial_financiado: null,
      monto_financiado: null,
      precio_total_financiado: null,
      partida_registral: '',
    };
    this.archivosNuevos = [];
    this.previsualizaciones = [];
    this.error.set(null);
    this.formularioAbierto.set(true);
  }

  abrirEditar(lote: Lote): void {
    this.loteEditando.set(lote);
    this.form = {
      id_manzana: lote.id_manzana,
      codigo: lote.codigo,
      ubicacion_lote: lote.ubicacion_lote ?? '',
      perimetro: lote.perimetro ? Number(lote.perimetro) : null,
      area_m2: Number(lote.area_m2),
      precio_m2_base: lote.precio_m2_base ? Number(lote.precio_m2_base) : null,
      precio_total_base: lote.precio_total_base ? Number(lote.precio_total_base) : null,
      precio_m2_contado: lote.precio_m2_contado ? Number(lote.precio_m2_contado) : null,
      precio_total_contado: lote.precio_total_contado ? Number(lote.precio_total_contado) : null,
      inicial_financiado: lote.inicial_financiado ? Number(lote.inicial_financiado) : null,
      monto_financiado: lote.monto_financiado ? Number(lote.monto_financiado) : null,
      precio_total_financiado: lote.precio_total_financiado ? Number(lote.precio_total_financiado) : null,
      partida_registral: lote.partida_registral ?? '',
    };
    this.archivosNuevos = [];
    this.previsualizaciones = [];
    this.error.set(null);
    this.formularioAbierto.set(true);
  }

  cerrarFormulario(): void {
    this.formularioAbierto.set(false);
    this.previsualizaciones.forEach((url) => URL.revokeObjectURL(url));
    this.archivosNuevos = [];
    this.previsualizaciones = [];
  }

  // ---- Selección de imágenes ----

  onImagenesSeleccionadas(event: Event): void {
    const input = event.target as HTMLInputElement;
    const files = Array.from(input.files ?? []);
    const tiposPermitidos = ['image/jpeg', 'image/png', 'image/webp'];

    for (const file of files) {
      if (!tiposPermitidos.includes(file.type)) {
        this.error.set('Solo se permiten imágenes JPG, PNG o WEBP');
        continue;
      }
      if (file.size > 8 * 1024 * 1024) {
        this.error.set('Cada imagen debe pesar menos de 8MB');
        continue;
      }
      this.archivosNuevos.push(file);
      this.previsualizaciones.push(URL.createObjectURL(file));
    }
    input.value = '';
  }

  quitarPrevisualizacion(index: number): void {
    URL.revokeObjectURL(this.previsualizaciones[index]);
    this.archivosNuevos.splice(index, 1);
    this.previsualizaciones.splice(index, 1);
  }

  urlImagenLote(relativa: string): string {
    if (relativa.startsWith('http://') || relativa.startsWith('https://')) return relativa;
    return this.api.apiUrl + relativa;
  }
  
  abrirImagen(relativa: string): void {
    this.imagenUrlActual.set(this.urlImagenLote(relativa));
    this.modalImagenAbierto.set(true);
  }

  cerrarImagen(): void {
    this.modalImagenAbierto.set(false);
    this.imagenUrlActual.set(null);
  }

  eliminarImagenExistente(idImagen: number): void {
    const lote = this.loteEditando();
    if (!lote || !confirm('¿Eliminar esta imagen?')) return;

    this.loteService.eliminarImagen(lote.id, idImagen).subscribe(() => {
      this.cargarLotes();
      const actualizado = { ...lote, imagenes: lote.imagenes.filter((img) => img.id !== idImagen) };
      this.loteEditando.set(actualizado);
    });
  }

  @HostListener('document:keydown.escape')
  onEscape(): void {
    if (this.modalImagenAbierto()) {
      this.cerrarImagen();
      return;
    }
    if (this.formularioAbierto()) {
      this.cerrarFormulario();
    }
  }

  // ---- Guardar (crear o editar) + subir imágenes ----

  guardarLote(): void {
    if (!this.idProyectoSeleccionado || !this.form.codigo || !this.form.area_m2) {
      this.error.set('Completa código y área del lote');
      return;
    }

    const loteActual = this.loteEditando();
    this.guardando.set(true);
    this.error.set(null);

    if (loteActual) {
      this.loteService
        .actualizar(loteActual.id, {
          ubicacion_lote: this.form.ubicacion_lote || undefined,
          perimetro: this.form.perimetro ?? undefined,
          area_m2: this.form.area_m2 ?? undefined,
          precio_m2_base: this.form.precio_m2_base ?? undefined,
          precio_total_base: this.form.precio_total_base ?? undefined,
          precio_m2_contado: this.form.precio_m2_contado ?? undefined,
          precio_total_contado: this.form.precio_total_contado ?? undefined,
          inicial_financiado: this.form.inicial_financiado ?? undefined,
          monto_financiado: this.form.monto_financiado ?? undefined,
          precio_total_financiado: this.form.precio_total_financiado ?? undefined,
          partida_registral: this.form.partida_registral || undefined,
        })
        .subscribe({
          next: () => this.subirImagenesPendientes(loteActual.id, loteActual.imagenes.length),
          error: (err) => {
            this.guardando.set(false);
            this.error.set(err?.error?.detail ?? 'Error al actualizar el lote');
          },
        });
    } else {
      if (!this.form.id_manzana) {
        this.guardando.set(false);
        this.error.set('Selecciona una manzana');
        return;
      }
      this.loteService
        .crear({
          id_proyecto: this.idProyectoSeleccionado,
          id_manzana: this.form.id_manzana,
          codigo: this.form.codigo,
          ubicacion_lote: this.form.ubicacion_lote || undefined,
          perimetro: this.form.perimetro ?? undefined,
          area_m2: this.form.area_m2!,
          precio_m2_base: this.form.precio_m2_base ?? undefined,
          precio_total_base: this.form.precio_total_base ?? undefined,
          precio_m2_contado: this.form.precio_m2_contado ?? undefined,
          precio_total_contado: this.form.precio_total_contado ?? undefined,
          inicial_financiado: this.form.inicial_financiado ?? undefined,
          monto_financiado: this.form.monto_financiado ?? undefined,
          precio_total_financiado: this.form.precio_total_financiado ?? undefined,
          partida_registral: this.form.partida_registral || undefined,
        })
        .subscribe({
          next: (lote) => this.subirImagenesPendientes(lote.id, 0),
          error: (err) => {
            this.guardando.set(false);
            this.error.set(err?.error?.detail ?? 'Error al crear el lote');
          },
        });
    }
  }

  private subirImagenesPendientes(idLote: number, imagenesExistentes: number): void {
    if (this.archivosNuevos.length === 0) {
      this.guardando.set(false);
      this.cerrarFormulario();
      this.cargarLotes();
      return;
    }

    this.subiendoImagenes.set(true);
    let completados = 0;

    this.archivosNuevos.forEach((archivo, index) => {
      const formData = new FormData();
      formData.append('archivo', archivo);

      this.loteService.subirImagen(formData).subscribe({
        next: (res) => {
          const esPortada = imagenesExistentes === 0 && index === 0;
          this.loteService.agregarImagen(idLote, res.url, esPortada, imagenesExistentes + index).subscribe({
            next: () => {
              completados++;
              if (completados === this.archivosNuevos.length) {
                this.subiendoImagenes.set(false);
                this.guardando.set(false);
                this.cerrarFormulario();
                this.cargarLotes();
              }
            },
            error: (err) => {
              console.error('Error al vincular imagen al lote:', err);
              this.error.set(err?.error?.detail ?? 'La imagen se subió pero no se pudo vincular al lote');
              completados++;
              if (completados === this.archivosNuevos.length) {
                this.subiendoImagenes.set(false);
                this.guardando.set(false);
              }
            },
          });
        },
        error: (err) => {
          console.error('Error al subir imagen:', err);
          this.error.set(err?.error?.detail ?? 'No se pudo subir la imagen');
          completados++;
          if (completados === this.archivosNuevos.length) {
            this.subiendoImagenes.set(false);
            this.guardando.set(false);
          }
        },
      });
    });
  }

  cambiarEstado(lote: Lote, estado: EstadoLote): void {
    this.api.patch(`/lotes/${lote.id}/estado`, { estado }).subscribe(() => this.cargarLotes());
  }
}