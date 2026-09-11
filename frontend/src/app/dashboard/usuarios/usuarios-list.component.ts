import { CommonModule } from '@angular/common';
import { Component, OnInit, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { ApiService } from '../../core/services/api.service';
import { UsuarioService } from '../../core/services/usuario.service';
import { Usuario, UsuarioCreate, UsuarioUpdate, Rol, Proyecto } from '../../core/models';

@Component({
  selector: 'app-usuarios-list',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './usuarios-list.component.html',
  styleUrl: './usuarios-list.component.css',
})
export class UsuariosListComponent implements OnInit {
  usuarios = signal<Usuario[]>([]);
  roles = signal<Rol[]>([]);
  proyectosDisponibles = signal<Proyecto[]>([]);
  cargando = signal(true);

  modalAbierto = signal(false);
  editando = signal<Usuario | null>(null);
  guardando = signal(false);
  error = signal<string | null>(null);

  nombre = '';
  correo = '';
  password = '';
  telefono = '';
  idRol: number | null = null;
  proyectosSeleccionados = new Set<number>();

  constructor(
    private usuarioService: UsuarioService,
    private api: ApiService
  ) {}

  ngOnInit(): void {
    this.cargarUsuarios();
    this.usuarioService.listarRoles().subscribe((roles) => this.roles.set(roles));
    this.api.get<Proyecto[]>('/proyectos').subscribe((proyectos) => this.proyectosDisponibles.set(proyectos));
  }

  cargarUsuarios(): void {
    this.cargando.set(true);
    this.usuarioService.listar().subscribe({
      next: (usuarios) => {
        this.usuarios.set(usuarios);
        this.cargando.set(false);
      },
      error: () => this.cargando.set(false),
    });
  }

  abrirNuevo(): void {
    this.editando.set(null);
    this.nombre = '';
    this.correo = '';
    this.password = '';
    this.telefono = '';
    this.idRol = null;
    this.proyectosSeleccionados = new Set();
    this.error.set(null);
    this.modalAbierto.set(true);
  }

  abrirEditar(usuario: Usuario): void {
    this.editando.set(usuario);
    this.nombre = usuario.nombre;
    this.correo = usuario.correo;
    this.password = '';
    this.telefono = usuario.telefono ?? '';
    this.idRol = usuario.id_rol;
    this.proyectosSeleccionados = new Set(usuario.proyectos);
    this.error.set(null);
    this.modalAbierto.set(true);
  }

  cerrarModal(): void {
    this.modalAbierto.set(false);
  }

  toggleProyecto(idProyecto: number): void {
    if (this.proyectosSeleccionados.has(idProyecto)) {
      this.proyectosSeleccionados.delete(idProyecto);
    } else {
      this.proyectosSeleccionados.add(idProyecto);
    }
  }

  estaSeleccionado(idProyecto: number): boolean {
    return this.proyectosSeleccionados.has(idProyecto);
  }

  guardar(): void {
    if (!this.nombre || !this.correo || !this.idRol) {
      this.error.set('Completa nombre, correo y rol');
      return;
    }

    const usuarioActual = this.editando();
    const proyectos = Array.from(this.proyectosSeleccionados);
    this.guardando.set(true);
    this.error.set(null);

    if (usuarioActual) {
      const payload: UsuarioUpdate = {
        nombre: this.nombre,
        correo: this.correo,
        telefono: this.telefono || undefined,
        id_rol: this.idRol,
        proyectos,
      };
      if (this.password) payload.password = this.password;

      this.usuarioService.actualizar(usuarioActual.id, payload).subscribe({
        next: () => {
          this.guardando.set(false);
          this.modalAbierto.set(false);
          this.cargarUsuarios();
        },
        error: (err) => {
          this.guardando.set(false);
          this.error.set(err?.error?.detail ?? 'Error al actualizar');
        },
      });
    } else {
      if (!this.password) {
        this.guardando.set(false);
        this.error.set('La contraseña es obligatoria para un usuario nuevo');
        return;
      }
      const payload: UsuarioCreate = {
        nombre: this.nombre,
        correo: this.correo,
        password: this.password,
        telefono: this.telefono || undefined,
        id_rol: this.idRol,
        proyectos,
      };

      this.usuarioService.crear(payload).subscribe({
        next: () => {
          this.guardando.set(false);
          this.modalAbierto.set(false);
          this.cargarUsuarios();
        },
        error: (err) => {
          this.guardando.set(false);
          this.error.set(err?.error?.detail ?? 'Error al crear');
        },
      });
    }
  }

  desactivar(usuario: Usuario): void {
    if (!confirm(`¿Desactivar a ${usuario.nombre}?`)) return;
    this.usuarioService.desactivar(usuario.id).subscribe(() => this.cargarUsuarios());
  }

  iniciales(nombre: string): string {
    return nombre
      .split(' ')
      .slice(0, 2)
      .map((p) => p.charAt(0).toUpperCase())
      .join('');
  }
}