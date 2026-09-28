import { Injectable } from '@angular/core';
import { ApiService } from './api.service';
import {
  Separacion,
  SeparacionCreate,
  SeparacionUpdate,
  ComprobanteCreate,
  DevolucionCreate,
  DevolucionResolver,
  EstadoSeparacion,
} from '../models';

@Injectable({ providedIn: 'root' })
export class SeparacionService {
  constructor(private api: ApiService) {}

  listar(idProyecto: number, estado?: EstadoSeparacion) {
    const params: Record<string, unknown> = { id_proyecto: idProyecto };
    if (estado) params['estado'] = estado;
    return this.api.get<Separacion[]>('/separaciones', params);
  }

  obtener(id: number) {
    return this.api.get<Separacion>(`/separaciones/${id}`);
  }

  crear(payload: SeparacionCreate) {
    return this.api.post<Separacion>('/separaciones', payload);
  }

  actualizar(id: number, payload: SeparacionUpdate) {
    return this.api.patch<Separacion>(`/separaciones/${id}`, payload);
  }

  validar(id: number) {
    return this.api.post<Separacion>(`/separaciones/${id}/validar`, {});
  }

  rechazar(id: number, motivo: string) {
    return this.api.post<Separacion>(`/separaciones/${id}/rechazar`, { motivo });
  }

  subirComprobante(id: number, payload: ComprobanteCreate) {
    return this.api.post<Separacion>(`/separaciones/${id}/comprobante`, payload);
  }

  convertir(id: number) {
    return this.api.post<Separacion>(`/separaciones/${id}/convertir`, {});
  }

  solicitarDevolucion(id: number, payload: DevolucionCreate) {
    return this.api.post<Separacion>(`/separaciones/${id}/devolucion`, payload);
  }

  resolverDevolucion(id: number, payload: DevolucionResolver) {
    return this.api.post<Separacion>(`/separaciones/${id}/devolucion/resolver`, payload);
  }

  liberar(id: number) {
    return this.api.post<Separacion>(`/separaciones/${id}/liberar`, {});
  }

  subirArchivo(formData: FormData) {
    return this.api.post<{ url: string }>('/uploads/comprobante', formData);
  }
}