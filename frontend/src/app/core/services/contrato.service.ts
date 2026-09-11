import { Injectable } from '@angular/core';
import { ApiService } from './api.service';
import { Contrato, ContratoCreate, CronogramaCuota, PagoCreate, Pago } from '../models';

@Injectable({ providedIn: 'root' })
export class ContratoService {
  constructor(private api: ApiService) {}

  listar(idProyecto: number) {
    return this.api.get<Contrato[]>('/contratos', { id_proyecto: idProyecto });
  }

  crear(payload: ContratoCreate) {
    return this.api.post<Contrato>('/contratos', payload);
  }

  cronograma(idContrato: number) {
    return this.api.get<CronogramaCuota[]>(`/contratos/${idContrato}/cronograma`);
  }

  registrarPago(idContrato: number, payload: PagoCreate) {
    return this.api.post<Pago>(`/contratos/${idContrato}/pagos`, payload);
  }

  subirComprobante(formData: FormData) {
    return this.api.post<{ url: string }>('/uploads/comprobante', formData);
  }

  listarPagos(idContrato: number) {
    return this.api.get<Pago[]>(`/contratos/${idContrato}/pagos`);
  }
}