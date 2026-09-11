import { Injectable } from '@angular/core';
import { ApiService } from './api.service';
import { Proyecto, ProyectoCreate, Manzana, ManzanaCreate } from '../models';

@Injectable({ providedIn: 'root' })
export class ProyectoService {
  constructor(private api: ApiService) {}

  listar() {
    return this.api.get<Proyecto[]>('/proyectos');
  }

  crear(payload: ProyectoCreate) {
    return this.api.post<Proyecto>('/proyectos', payload);
  }

  listarManzanas(idProyecto: number) {
    return this.api.get<Manzana[]>(`/proyectos/${idProyecto}/manzanas`);
  }

  crearManzana(payload: ManzanaCreate) {
    return this.api.post<Manzana>('/proyectos/manzanas', payload);
  }
}