import { Injectable } from '@angular/core';
import { ApiService } from './api.service';
import { Venta, VentaCreate, DocumentoUbicacion, DocumentoUbicacionCreate, EvaluacionVenta, AutorizacionVenta } from '../models';

@Injectable({ providedIn: 'root' })
export class VentaService {
  constructor(private api: ApiService) {}

  crearDesdeSeparacion(idSeparacion: number, payload: VentaCreate) {
    return this.api.post<Venta>(`/ventas/desde-separacion/${idSeparacion}`, payload);
  }

  obtener(id: number) {
    return this.api.get<Venta>(`/ventas/${id}`);
  }

  generarDocumento(id: number, firmante: 'gerente' | 'apoderado' = 'gerente') {
    return this.api.post<Venta>(`/ventas/${id}/generar-documento`, { firmante });
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

  evaluar(idSeparacion: number, payload: VentaCreate) {
    return this.api.post<EvaluacionVenta>(`/ventas/evaluar/${idSeparacion}`, payload);
  }

  solicitarAutorizacion(idSeparacion: number, payload: VentaCreate) {
    return this.api.post<AutorizacionVenta>(`/ventas/solicitar-autorizacion/${idSeparacion}`, payload);
  }

  listarAutorizaciones(idSeparacion: number) {
    return this.api.get<AutorizacionVenta[]>('/ventas/autorizaciones', { id_separacion: idSeparacion });
  }

  resolverAutorizacion(id: number, aprobar: boolean, respuesta?: string) {
    return this.api.post<AutorizacionVenta>(`/ventas/autorizaciones/${id}/resolver`, { aprobar, respuesta });
  }

  crearDesdeAutorizacion(id: number) {
    return this.api.post<Venta>(`/ventas/autorizaciones/${id}/crear-venta`, {});
  }

  ventaDeContrato(idContrato: number) {
    return this.api.get<{ id_venta: number | null }>(`/ventas/por-contrato/${idContrato}`);
  }

  registrarContrato(id: number) {
    return this.api.post<Venta>(`/ventas/${id}/registrar-contrato`, {});
  }


  subirDocumentoLegal(idVenta: number, tipo: 'escritura' | 'titulo', url: string) {
    return this.api.post<Venta>(`/ventas/${idVenta}/documento-legal`, { tipo, url });
  }
}