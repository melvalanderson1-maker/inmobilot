import { Injectable } from '@angular/core';
import { ApiService } from './api.service';
import { Venta, VentaCreate, DocumentoUbicacion, DocumentoUbicacionCreate } from '../models';

@Injectable({ providedIn: 'root' })
export class VentaService {
  constructor(private api: ApiService) {}

  crearDesdeSeparacion(idSeparacion: number, payload: VentaCreate) {
    return this.api.post<Venta>(`/ventas/desde-separacion/${idSeparacion}`, payload);
  }

  obtener(id: number) {
    return this.api.get<Venta>(`/ventas/${id}`);
  }

  generarDocumento(id: number) {
    return this.api.post<Venta>(`/ventas/${id}/generar-documento`, {});
  }

  subirDocumentoFirmado(id: number, url: string) {
    return this.api.post<Venta>(`/ventas/${id}/documento-firmado`, { url });
  }

  registrarUbicacion(id: number, payload: DocumentoUbicacionCreate) {
    return this.api.post<DocumentoUbicacion>(`/ventas/${id}/ubicacion-documento`, payload);
  }

  subirArchivo(formData: FormData) {
    return this.api.post<{ url: string }>('/uploads/comprobante', formData);
  }

  registrarContrato(id: number) {
    return this.api.post<Venta>(`/ventas/${id}/registrar-contrato`, {});
  }
}