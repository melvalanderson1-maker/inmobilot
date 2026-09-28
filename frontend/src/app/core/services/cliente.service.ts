import { Injectable } from '@angular/core';
import { ApiService } from './api.service';
import { Cliente, ClienteCreate, ClienteDetalle, ClienteUpdate } from '../models';

@Injectable({ providedIn: 'root' })
export class ClienteService {
  constructor(private api: ApiService) {}

  buscarPorDocumento(documento: string) {
    return this.api.get<Cliente | null>('/clientes/buscar', { documento });
  }

  listar(filtros?: { busqueda?: string; tipo_persona?: string; activo?: boolean }) {
    return this.api.get<Cliente[]>('/clientes', filtros as Record<string, unknown>);
  }

  obtener(id: number) {
    return this.api.get<ClienteDetalle>(`/clientes/${id}`);
  }

  crear(payload: ClienteCreate) {
    return this.api.post<Cliente>('/clientes', payload);
  }

  actualizar(id: number, payload: ClienteUpdate) {
    return this.api.patch<Cliente>(`/clientes/${id}`, payload);
  }

  subirArchivo(formData: FormData) {
    return this.api.post<{ url: string }>('/uploads/comprobante', formData);
  }
}