import { Injectable } from '@angular/core';
import { ApiService } from './api.service';
import { Pago, PagoCola, PagoComprobanteIn } from '../models';

@Injectable({ providedIn: 'root' })
export class PagoService {
  constructor(private api: ApiService) {}

  listar(idProyecto: number) {
    return this.api.get<PagoCola[]>('/pagos', { id_proyecto: idProyecto });
  }

  validar(id: number) {
    return this.api.post<Pago>(`/pagos/${id}/validar`, {});
  }

  rechazar(id: number, motivo: string) {
    return this.api.post<Pago>(`/pagos/${id}/rechazar`, { motivo });
  }

  subirComprobante(id: number, payload: PagoComprobanteIn) {
    return this.api.post<Pago>(`/pagos/${id}/comprobante`, payload);
  }

  subirArchivo(formData: FormData) {
    return this.api.post<{ url: string }>('/uploads/comprobante', formData);
  }
}