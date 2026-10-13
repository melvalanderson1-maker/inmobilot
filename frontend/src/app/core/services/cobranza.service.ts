import { Injectable } from '@angular/core';
import { ApiService } from './api.service';
import { CobranzaFila, Venta } from '../models';

@Injectable({ providedIn: 'root' })
export class CobranzaService {
  constructor(private api: ApiService) {}

  resumen(idProyecto: number) {
    return this.api.get<CobranzaFila[]>('/cobranza/resumen', { id_proyecto: idProyecto });
  }

  recalcular(idContrato: number) {
    return this.api.post<{ mensaje: string }>(`/cobranza/contratos/${idContrato}/recalcular-cuotas`, {});
  }

  cancelar(idContrato: number) {
    return this.api.post<{ mensaje: string }>(`/cobranza/contratos/${idContrato}/cancelar`, {});
  }

  finalizarVenta(idVenta: number) {
    return this.api.post<Venta>(`/cobranza/ventas/${idVenta}/finalizar`, {});
  }
}