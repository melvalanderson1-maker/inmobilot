import { CommonModule } from '@angular/common';
import { Component, HostListener, OnDestroy, OnInit, computed, effect, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { SocketService } from '../../core/services/socket.service';
import { LoteService } from '../../core/services/lote.service';
import { TenantService } from '../../core/services/tenant.service';
import { ToastService } from '../../core/services/toast.service';
import { LoaderService } from '../../core/services/loader.service';
import { ConfirmModalService } from '../../core/services/confirm-modal.service';
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
    frontis: '',
    perimetro: null as number | null,
    area_m2: null as number | null,
    precio_m2_base: null as number | null,
    precio_total_base: null as number | null,
    precio_m2_contado: null as number | null,
    precio_total_contado: null as number | null,
    precio_m2_financiado: null as number | null,
    inicial_financiado: null as number | null,
    monto_financiado: null as number | null,
    precio_total_financiado: null as number | null,
    inicial_financiado_60c: null as number | null,
    cuota_mensual_60c: null as number | null,
    partida_registral: '',
  };

  // ---- Filtros y KPIs ----
  filtroEstado = signal<'todos' | EstadoLote>('todos');
  filtroBusqueda = signal('');
  filtroPrecioMin = signal<number | null>(null);
  filtroPrecioMax = signal<number | null>(null);

  // El signo de grado (°) y el ordinal masculino (º) se ven casi idénticos
  // pero son caracteres distintos: los unificamos antes de comparar, para
  // que la búsqueda encuentre el lote sin importar cuál haya tecleado el usuario.
  private normalizarTexto(valor: string): string {
    return valor.toLowerCase().replace(/[°º]/g, '°');
  }

  lotesFiltrados = computed(() => {
    const estado = this.filtroEstado();
    const busqueda = this.normalizarTexto(this.filtroBusqueda().trim());
    const min = this.filtroPrecioMin();
    const max = this.filtroPrecioMax();

    return this.lotes().filter((l) => {
      if (estado !== 'todos' && l.estado !== estado) return false;
      if (busqueda) {
        const texto = this.normalizarTexto(
          `${l.codigo} ${l.ubicacion_lote ?? ''} ${l.partida_registral ?? ''}`
        );
        if (!texto.includes(busqueda)) return false;
      }
      const precio = l.precio_total_contado ?? l.precio_total_base ?? 0;
      if (min !== null && precio < min) return false;
      if (max !== null && precio > max) return false;
      return true;
    });
  });

  // ---- Paginación (solo afecta la vista de tabla) ----
  paginaActual = signal(1);
  itemsPorPagina = 20;

  totalPaginas = computed(() => Math.max(1, Math.ceil(this.lotesFiltrados().length / this.itemsPorPagina)));

  lotesPaginados = computed(() => {
    const pagina = this.paginaActual();
    const inicio = (pagina - 1) * this.itemsPorPagina;
    return this.lotesFiltrados().slice(inicio, inicio + this.itemsPorPagina);
  });

  irAPagina(pagina: number): void {
    const total = this.totalPaginas();
    if (pagina < 1 || pagina > total) return;
    this.paginaActual.set(pagina);
  }

  kpiTotal = computed(() => this.lotes().length);
  kpiDisponibles = computed(() => this.lotes().filter((l) => l.estado === 'libre').length);
  kpiSeparados = computed(() => this.lotes().filter((l) => l.estado === 'separado').length);
  kpiBloqueados = computed(() => this.lotes().filter((l) => l.estado === 'bloqueado').length);
  kpiVendidos = computed(() => this.lotes().filter((l) => l.estado === 'vendido').length);
  kpiValorInventario = computed(() =>
    this.lotes().reduce((acc, l) => acc + Number(l.precio_total_contado ?? l.precio_total_base ?? 0), 0)
  );

  limpiarFiltros(): void {
    this.filtroEstado.set('todos');
    this.filtroBusqueda.set('');
    this.filtroPrecioMin.set(null);
    this.filtroPrecioMax.set(null);
    this.paginaActual.set(1);
  }

  // ---- Imágenes ----
  archivosNuevos: File[] = [];
  previsualizaciones: string[] = [];
  subiendoImagenes = signal(false);

  // ---- Visor de imagen ----
  modalImagenAbierto = signal(false);
  imagenUrlActual = signal<string | null>(null);

  // ---- Dropdown de estado (en la tabla) ----
  menuEstadoAbierto = signal<number | null>(null);

  constructor(
    private api: ApiService,
    public auth: AuthService,
    private socket: SocketService,
    private loteService: LoteService,
    public tenant: TenantService,
    private toastService: ToastService,
    private loader: LoaderService,
    private confirmModal: ConfirmModalService
  ) {
    // Resetea a la página 1 cada vez que cambia cualquier filtro,
    // para no quedar "atrapado" en una página que ya no existe.
    effect(() => {
      this.filtroEstado();
      this.filtroBusqueda();
      this.filtroPrecioMin();
      this.filtroPrecioMax();
      this.paginaActual.set(1);
    });
  }
  // ---- Ubicar en el mapa (clic directo sobre la imagen) ----
  modalMapaAbierto = signal(false);
  loteUbicando = signal<Lote | null>(null);
  guardandoUbicacion = signal(false);

  urlMaqueta(): string | null {
    const url = this.tenant.config()?.mapa_url;
    if (!url) return null;
    if (url.startsWith('http')) return url;
    return this.api.apiUrl + url;
  }

  abrirUbicarMapa(lote: Lote): void {
    this.loteUbicando.set(lote);
    this.modalMapaAbierto.set(true);
  }

  cerrarUbicarMapa(): void {
    this.modalMapaAbierto.set(false);
    this.loteUbicando.set(null);
  }

  onClickMaqueta(event: MouseEvent): void {
    const lote = this.loteUbicando();
    if (!lote) return;
    const target = event.currentTarget as HTMLElement;
    const rect = target.getBoundingClientRect();
    const x = ((event.clientX - rect.left) / rect.width) * 100;
    const y = ((event.clientY - rect.top) / rect.height) * 100;

    this.guardandoUbicacion.set(true);
    this.loteService.actualizar(lote.id, { mapa_x: Math.round(x * 100) / 100, mapa_y: Math.round(y * 100) / 100 } as any)
      .subscribe({
        next: () => {
          this.guardandoUbicacion.set(false);
          this.cargarLotes();
          this.cerrarUbicarMapa();
        },
        error: () => this.guardandoUbicacion.set(false),
      });
  }

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
    this.paginaActual.set(1);
    this.cargarManzanas();
    this.cargarLotes();
  }

  cargarManzanas(): void {
    this.api
      .get<Manzana[]>(`/proyectos/${this.idProyectoSeleccionado}/manzanas`)
      .subscribe((res) => this.manzanas.set(res));
  }

  onManzanaSeleccionada(): void {
    // Mientras el lote no tenga su propia partida individual (proceso de
    // independización en SUNARP), legalmente usa la partida matriz de su
    // etapa. Lo sugerimos como valor por defecto — el usuario lo puede
    // sobrescribir apenas el lote consiga su partida propia.
    if (this.loteEditando()) return; // no pisar datos reales al editar
    const manzana = this.manzanas().find((m) => m.id === this.form.id_manzana);
    const partidaEtapa = manzana?.etapa?.partida_registral;
    if (partidaEtapa && !this.form.partida_registral) {
      this.form.partida_registral = partidaEtapa;
    }
  }

  cargarLotes(): void {
    // Solo mostramos "Cargando..." si es la primera carga (lista vacía).
    // En recargas por socket o cambios de estado, no ocultamos la tabla
    // para evitar el parpadeo.
    if (this.lotes().length === 0) {
      this.cargando.set(true);
    }
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
      frontis: '',
      perimetro: null,
      area_m2: null,
      precio_m2_base: null,
      precio_total_base: null,
      precio_m2_contado: null,
      precio_total_contado: null,
      precio_m2_financiado: null,
      inicial_financiado: null,
      monto_financiado: null,
      precio_total_financiado: null,
      inicial_financiado_60c: null,
      cuota_mensual_60c: null,
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
      frontis: lote.frontis ?? '',
      perimetro: lote.perimetro ? Number(lote.perimetro) : null,
      area_m2: Number(lote.area_m2),
      precio_m2_base: lote.precio_m2_base ? Number(lote.precio_m2_base) : null,
      precio_total_base: lote.precio_total_base ? Number(lote.precio_total_base) : null,
      precio_m2_contado: lote.precio_m2_contado ? Number(lote.precio_m2_contado) : null,
      precio_total_contado: lote.precio_total_contado ? Number(lote.precio_total_contado) : null,
      precio_m2_financiado: lote.precio_m2_financiado ? Number(lote.precio_m2_financiado) : null,
      inicial_financiado: lote.inicial_financiado ? Number(lote.inicial_financiado) : null,
      monto_financiado: lote.monto_financiado ? Number(lote.monto_financiado) : null,
      precio_total_financiado: lote.precio_total_financiado ? Number(lote.precio_total_financiado) : null,
      inicial_financiado_60c: (lote as any).inicial_financiado_60c ? Number((lote as any).inicial_financiado_60c) : null,
      cuota_mensual_60c: (lote as any).cuota_mensual_60c ? Number((lote as any).cuota_mensual_60c) : null,
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

  inicialesUsuarioLote(nombre: string | undefined | null): string {
    if (!nombre) return '';
    return nombre
      .trim()
      .split(/\s+/)
      .slice(0, 2)
      .map((palabra) => palabra[0])
      .join('')
      .toUpperCase();
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
    if (this.menuEstadoAbierto() !== null) {
      this.cerrarMenuEstado();
      return;
    }
    if (this.modalImagenAbierto()) {
      this.cerrarImagen();
      return;
    }
    if (this.formularioAbierto()) {
      this.cerrarFormulario();
    }
  }

  @HostListener('document:click')
  onDocumentClick(): void {
    if (this.menuEstadoAbierto() !== null) {
      this.menuEstadoAbierto.set(null);
    }
  }

  toggleMenuEstado(idLote: number, event: MouseEvent): void {
    event.stopPropagation();
    this.menuEstadoAbierto.update((actual) => (actual === idLote ? null : idLote));
  }

  cerrarMenuEstado(): void {
    this.menuEstadoAbierto.set(null);
  }

  seleccionarEstado(lote: Lote, estado: string): void {
    this.cerrarMenuEstado();
    if (estado === lote.estado) return;
    this.cambiarEstado(lote, estado as EstadoLote);
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
          frontis: this.form.frontis || undefined,
          perimetro: this.form.perimetro ?? undefined,
          area_m2: this.form.area_m2 ?? undefined,
          precio_m2_base: this.form.precio_m2_base ?? undefined,
          precio_total_base: this.form.precio_total_base ?? undefined,
          precio_m2_contado: this.form.precio_m2_contado ?? undefined,
          precio_total_contado: this.form.precio_total_contado ?? undefined,
          precio_m2_financiado: this.form.precio_m2_financiado ?? undefined,
          inicial_financiado: this.form.inicial_financiado ?? undefined,
          monto_financiado: this.form.monto_financiado ?? undefined,
          precio_total_financiado: this.form.precio_total_financiado ?? undefined,
          inicial_financiado_60c: this.form.inicial_financiado_60c ?? undefined,
          cuota_mensual_60c: this.form.cuota_mensual_60c ?? undefined,
          partida_registral: this.form.partida_registral || undefined,
        })
        .subscribe({ 
          next: (loteActualizado) => this.subirImagenesPendientes(loteActual.id, loteActual.imagenes.length, loteActualizado.actualizado_por_nombre),
          error: (err) => { 
            this.guardando.set(false); 
            const mensaje = err?.error?.detail ?? 'Error al actualizar el lote';
            this.error.set(mensaje);
            this.toastService.error(mensaje);
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
          frontis: this.form.frontis || undefined,
          perimetro: this.form.perimetro ?? undefined,
          area_m2: this.form.area_m2!,
          precio_m2_base: this.form.precio_m2_base ?? undefined,
          precio_total_base: this.form.precio_total_base ?? undefined,
          precio_m2_contado: this.form.precio_m2_contado ?? undefined,
          precio_total_contado: this.form.precio_total_contado ?? undefined,
          precio_m2_financiado: this.form.precio_m2_financiado ?? undefined,
          inicial_financiado: this.form.inicial_financiado ?? undefined,
          monto_financiado: this.form.monto_financiado ?? undefined,
          precio_total_financiado: this.form.precio_total_financiado ?? undefined,
          inicial_financiado_60c: this.form.inicial_financiado_60c ?? undefined,
          cuota_mensual_60c: this.form.cuota_mensual_60c ?? undefined,
          partida_registral: this.form.partida_registral || undefined,
        })
        .subscribe({ 
          next: (lote) => this.subirImagenesPendientes(lote.id, 0, lote.creado_por_nombre),
          error: (err) => { 
            this.guardando.set(false); 
            const mensaje = err?.error?.detail ?? 'Error al crear el lote';
            this.error.set(mensaje);
            this.toastService.error(mensaje);
          }, 
        });
    }
  }

  private subirImagenesPendientes(idLote: number, imagenesExistentes: number, nombreUsuario?: string): void {
    if (this.archivosNuevos.length === 0) { 
      this.guardando.set(false); 
      this.cerrarFormulario();
      this.cargarLotes();

      const sufijo = nombreUsuario ? ` por ${nombreUsuario}` : '';
      const mensaje = this.loteEditando()
        ? `Lote actualizado correctamente${sufijo}`
        : `Lote creado correctamente${sufijo}`;

      this.toastService.exito(mensaje);

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

              const sufijo = nombreUsuario ? ` por ${nombreUsuario}` : '';
              const mensaje = this.loteEditando()
                ? `Lote actualizado correctamente${sufijo}`
                : `Lote creado correctamente${sufijo}`;

              this.toastService.exito(mensaje);
            }
            },
              error: (err) => { 
                console.error('Error al vincular imagen al lote:', err);

                const mensaje =
                  err?.error?.detail ??
                  'La imagen se subió pero no se pudo vincular al lote';

                this.error.set(mensaje);
                this.toastService.error(mensaje);

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

          const mensaje = err?.error?.detail ?? 'No se pudo subir la imagen';

          this.error.set(mensaje);
          this.toastService.error(mensaje);

          completados++;

          if (completados === this.archivosNuevos.length) { 
            this.subiendoImagenes.set(false); 
            this.guardando.set(false); 
          } 
        },
      });
    });
  }

  
async cambiarEstado(lote: Lote, estado: EstadoLote, selectElement?: HTMLSelectElement): Promise<void> {
  if (estado === lote.estado) {
    if (selectElement) selectElement.value = '';
    return;
  }

  const confirmado = await this.confirmModal.confirm(
    'Cambiar estado del lote',
    `¿Confirmas cambiar el estado del lote ${lote.codigo} a "${estado}"?`
  );

  // Apenas se resuelve el modal (confirmes o canceles), el select
  // vuelve a mostrar "Cambiar estado" — así nunca queda "pegado"
  // en una opción que en realidad no se aplicó.
  if (selectElement) selectElement.value = '';

  if (!confirmado) return;

    const estadoAnterior = lote.estado;

    // Actualización optimista: cambiamos el estado en memoria de inmediato,
    // sin recargar toda la lista (evita el parpadeo de la tabla).
    this.lotes.update((lista) =>
      lista.map((l) => (l.id === lote.id ? { ...l, estado } : l))
    );

    this.loader.show('Actualizando estado del lote...');

    this.api.patch<Lote>(`/lotes/${lote.id}/estado`, { estado }).subscribe({
      next: (loteActualizado) => {
        this.loader.hide();
        const sufijo = loteActualizado.actualizado_por_nombre ? ` por ${loteActualizado.actualizado_por_nombre}` : '';
        this.toastService.exito(`Estado del lote ${lote.codigo} actualizado correctamente${sufijo}`);
      },
      error: (err) => {
        this.loader.hide();
        // Si falla, revertimos al estado anterior
        this.lotes.update((lista) =>
          lista.map((l) => (l.id === lote.id ? { ...l, estado: estadoAnterior } : l))
        );
        const mensaje = err?.error?.detail ?? 'No se pudo cambiar el estado del lote';
        this.toastService.error(mensaje);
      },
    });
  }
}