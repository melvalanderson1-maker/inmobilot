import { Injectable } from '@angular/core';
import { ApiService } from './api.service';
import { Cliente, ClienteCreate } from '../models';

@Injectable({ providedIn: 'root' })
export class ClienteService {
  constructor(private api: ApiService) {}

  buscarPorDocumento(documento: string) {
    return this.api.get<Cliente | null>('/clientes/buscar', { documento });
  }

  crear(payload: ClienteCreate) {
    return this.api.post<Cliente>('/clientes', payload);
  }
}