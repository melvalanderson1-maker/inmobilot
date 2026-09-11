import { CommonModule } from '@angular/common';
import { Component, OnInit, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { ProyectoService } from '../../core/services/proyecto.service';
import { Proyecto, ProyectoCreate, Manzana } from '../../core/models';

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
  guardandoManzana = signal<number | null>(null);

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
    if (!this.manzanasPorProyecto()[proyecto.id]) {
      this.cargarManzanas(proyecto.id);
    }
  }

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
    if (!nombre) return;

    this.guardandoManzana.set(idProyecto);
    this.proyectoService.crearManzana({ id_proyecto: idProyecto, nombre }).subscribe({
      next: () => {
        this.nombreManzanaNueva[idProyecto] = '';
        this.guardandoManzana.set(null);
        this.cargarManzanas(idProyecto);
      },
      error: () => this.guardandoManzana.set(null),
    });
  }

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