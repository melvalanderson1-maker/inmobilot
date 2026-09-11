import { Injectable } from '@angular/core';
import { ApiService } from './api.service';
import { Usuario, UsuarioCreate, UsuarioUpdate, Rol } from '../models';

@Injectable({ providedIn: 'root' })
export class UsuarioService {
  constructor(private api: ApiService) {}

  listar() {
    return this.api.get<Usuario[]>('/usuarios');
  }

  obtener(id: number) {
    return this.api.get<Usuario>(`/usuarios/${id}`);
  }

  crear(payload: UsuarioCreate) {
    return this.api.post<Usuario>('/usuarios', payload);
  }

  actualizar(id: number, payload: UsuarioUpdate) {
    return this.api.patch<Usuario>(`/usuarios/${id}`, payload);
  }

  desactivar(id: number) {
    return this.api.delete<void>(`/usuarios/${id}`);
  }

  listarRoles() {
    return this.api.get<Rol[]>('/usuarios/roles/lista');
  }
}