import { Injectable } from '@angular/core';

import { Proforma, ProformaCreate } from '../models';
import { ApiService } from './api.service';

@Injectable({ providedIn: 'root' })
export class ProformaService {
  constructor(private api: ApiService) {}

  listar(idProyecto: number, buscar?: string) {
    return this.api.get<Proforma[]>('/proformas', { id_proyecto: idProyecto, ...(buscar ? { buscar } : {}) });
  }

  obtener(id: number) {
    return this.api.get<Proforma>(`/proformas/${id}`);
  }

  crear(payload: ProformaCreate) {
    return this.api.post<Proforma>('/proformas', payload);
  }
}