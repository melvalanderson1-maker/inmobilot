import { CommonModule } from '@angular/common';
import { Component, OnInit, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { ProyectoService } from '../../core/services/proyecto.service';
import {
  Proyecto, ProyectoCreate, Manzana, Etapa, EtapaCreate, EtapaUpdate,
} from '../../core/models';

@Component({
  selector: 'app-proyectos-list',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './proyectos-list.component.html',
  styleUrl: './proyectos-list.component.css',
})
export class ProyectosListComponent implements OnInit {
  proyectos = signal<Proyecto[]>([]);
  cargando = signal(true);

  expandido = signal<number | null>(null);
  manzanasPorProyecto = signal<Partial<Record<number, Manzana[]>>>({});
  cargandoManzanas = signal<number | null>(null);

  etapasPorProyecto = signal<Partial<Record<number, Etapa[]>>>({});
  cargandoEtapas = signal<number | null>(null);

  modalAbierto = signal(false);
  guardando = signal(false);
  error = signal<string | null>(null);

  nombre = '';
  slug = '';
  slugTocadoManualmente = false;
  departamento = '';
  provincia = '';
  distrito = '';
  descripcion = '';
  moneda = 'PEN';

  nombreManzanaNueva: Record<number, string> = {};
  etapaSeleccionadaManzana: Record<number, number | null> = {};
  guardandoManzana = signal<number | null>(null);

  // ---- Modal Etapa ----
  modalEtapaAbierto = signal(false);
  etapaEditando = signal<Etapa | null>(null);
  guardandoEtapa = signal(false);
  errorEtapa = signal<string | null>(null);
  idProyectoParaEtapa: number | null = null;

  formEtapa = {
    nombre: '',
    partida_registral: '',
    sunarp_url: '',
    orden: 0,
  };

  constructor(private proyectoService: ProyectoService) {}

  ngOnInit(): void {
    this.cargarProyectos();
  }

  cargarProyectos(): void {
    this.cargando.set(true);
    this.proyectoService.listar().subscribe({
      next: (proyectos) => {
        this.proyectos.set(proyectos);
        this.cargando.set(false);
      },
      error: () => this.cargando.set(false),
    });
  }

  toggleExpandir(proyecto: Proyecto): void {
    if (this.expandido() === proyecto.id) {
      this.expandido.set(null);
      return;
    }
    this.expandido.set(proyecto.id);
    if (!this.etapasPorProyecto()[proyecto.id]) {
      this.cargarEtapas(proyecto.id);
    }
    if (!this.manzanasPorProyecto()[proyecto.id]) {
      this.cargarManzanas(proyecto.id);
    }
  }

  // ---- Etapas ----

  cargarEtapas(idProyecto: number): void {
    this.cargandoEtapas.set(idProyecto);
    this.proyectoService.listarEtapas(idProyecto).subscribe({
      next: (etapas) => {
        this.etapasPorProyecto.update((actual) => ({ ...actual, [idProyecto]: etapas }));
        this.cargandoEtapas.set(null);
      },
      error: () => this.cargandoEtapas.set(null),
    });
  }

  abrirNuevaEtapa(idProyecto: number): void {
    this.idProyectoParaEtapa = idProyecto;
    this.etapaEditando.set(null);
    this.formEtapa = { nombre: '', partida_registral: '', sunarp_url: '', orden: 0 };
    this.errorEtapa.set(null);
    this.modalEtapaAbierto.set(true);
  }

  abrirEditarEtapa(etapa: Etapa, idProyecto: number): void {
    this.idProyectoParaEtapa = idProyecto;
    this.etapaEditando.set(etapa);
    this.formEtapa = {
      nombre: etapa.nombre,
      partida_registral: etapa.partida_registral,
      sunarp_url: etapa.sunarp_url ?? '',
      orden: etapa.orden ?? 0,
    };
    this.errorEtapa.set(null);
    this.modalEtapaAbierto.set(true);
  }

  cerrarModalEtapa(): void {
    this.modalEtapaAbierto.set(false);
  }

  guardarEtapa(): void {
    if (!this.formEtapa.nombre || !this.formEtapa.partida_registral) {
      this.errorEtapa.set('El nombre y la partida registral son obligatorios');
      return;
    }
    if (!this.idProyectoParaEtapa) return;

    this.guardandoEtapa.set(true);
    this.errorEtapa.set(null);

    const etapaActual = this.etapaEditando();

    if (etapaActual) {
      const payload: EtapaUpdate = {
        nombre: this.formEtapa.nombre,
        partida_registral: this.formEtapa.partida_registral,
        sunarp_url: this.formEtapa.sunarp_url || undefined,
        orden: this.formEtapa.orden,
      };
      this.proyectoService.actualizarEtapa(etapaActual.id, payload).subscribe({
        next: () => {
          this.guardandoEtapa.set(false);
          this.modalEtapaAbierto.set(false);
          this.cargarEtapas(this.idProyectoParaEtapa!);
        },
        error: (err: any) => {
          this.guardandoEtapa.set(false);
          this.errorEtapa.set(err?.error?.detail ?? 'Error al actualizar la etapa');
        },
      });
    } else {
      const payload: EtapaCreate = {
        id_proyecto: this.idProyectoParaEtapa,
        nombre: this.formEtapa.nombre,
        partida_registral: this.formEtapa.partida_registral,
        sunarp_url: this.formEtapa.sunarp_url || undefined,
        orden: this.formEtapa.orden,
      };
      this.proyectoService.crearEtapa(payload).subscribe({
        next: () => {
          this.guardandoEtapa.set(false);
          this.modalEtapaAbierto.set(false);
          this.cargarEtapas(this.idProyectoParaEtapa!);
        },
        error: (err) => {
          this.guardandoEtapa.set(false);
          this.errorEtapa.set(err?.error?.detail ?? 'Error al crear la etapa');
        },
      });
    }
  }

  // ---- Manzanas ----

  cargarManzanas(idProyecto: number): void {
    this.cargandoManzanas.set(idProyecto);
    this.proyectoService.listarManzanas(idProyecto).subscribe({
      next: (manzanas) => {
        this.manzanasPorProyecto.update((actual) => ({ ...actual, [idProyecto]: manzanas }));
        this.cargandoManzanas.set(null);
      },
      error: () => this.cargandoManzanas.set(null),
    });
  }

  crearManzana(idProyecto: number): void {
    const nombre = (this.nombreManzanaNueva[idProyecto] ?? '').trim();
    const idEtapa = this.etapaSeleccionadaManzana[idProyecto];

    if (!nombre) return;
    if (!idEtapa) {
      this.error.set('Selecciona una etapa antes de agregar la manzana');
      return;
    }

    this.guardandoManzana.set(idProyecto);
    this.proyectoService
      .crearManzana({ id_proyecto: idProyecto, id_etapa: idEtapa, nombre })
      .subscribe({
        next: () => {
          this.nombreManzanaNueva[idProyecto] = '';
          this.guardandoManzana.set(null);
          this.cargarManzanas(idProyecto);
        },
        error: () => this.guardandoManzana.set(null),
      });
  }

  // ---- Proyecto (sin cambios) ----

  abrirNuevoProyecto(): void {
    this.nombre = '';
    this.slug = '';
    this.slugTocadoManualmente = false;
    this.departamento = '';
    this.provincia = '';
    this.distrito = '';
    this.descripcion = '';
    this.moneda = 'PEN';
    this.error.set(null);
    this.modalAbierto.set(true);
  }

  cerrarModal(): void {
    this.modalAbierto.set(false);
  }

  onNombreChange(): void {
    if (!this.slugTocadoManualmente) {
      this.slug = this.generarSlug(this.nombre);
    }
  }

  onSlugChange(): void {
    this.slugTocadoManualmente = true;
  }

  private generarSlug(texto: string): string {
    return texto
      .toLowerCase()
      .normalize('NFD')
      .replace(/[\u0300-\u036f]/g, '')
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/(^-|-$)/g, '');
  }

  guardarProyecto(): void {
    if (!this.nombre || !this.slug) {
      this.error.set('El nombre y el slug son obligatorios');
      return;
    }

    const payload: ProyectoCreate = {
      nombre: this.nombre,
      slug: this.slug,
      departamento: this.departamento || undefined,
      provincia: this.provincia || undefined,
      distrito: this.distrito || undefined,
      descripcion: this.descripcion || undefined,
      moneda: this.moneda || 'PEN',
    };

    this.guardando.set(true);
    this.error.set(null);

    this.proyectoService.crear(payload).subscribe({
      next: () => {
        this.guardando.set(false);
        this.modalAbierto.set(false);
        this.cargarProyectos();
      },
      error: (err) => {
        this.guardando.set(false);
        this.error.set(err?.error?.detail ?? 'Error al crear el proyecto');
      },
    });
  }
}