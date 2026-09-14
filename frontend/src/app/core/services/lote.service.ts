import { Injectable } from '@angular/core';
import { ApiService } from './api.service';
import { Lote, LoteImagen } from '../models';

export interface LoteCreate {
  id_proyecto: number;
  id_manzana: number;
  codigo: string;
  ubicacion_lote?: string;
  perimetro?: number;
  area_m2: number;
  precio_m2_base?: number;
  precio_total_base?: number;
  precio_m2_contado?: number;
  precio_total_contado?: number;
  inicial_financiado?: number;
  monto_financiado?: number;
  precio_total_financiado?: number;
  partida_registral?: string;
}

export interface LoteUpdate {
  ubicacion_lote?: string;
  perimetro?: number;
  area_m2?: number;
  precio_m2_base?: number;
  precio_total_base?: number;
  precio_m2_contado?: number;
  precio_total_contado?: number;
  inicial_financiado?: number;
  monto_financiado?: number;
  precio_total_financiado?: number;
  partida_registral?: string;
}

@Injectable({ providedIn: 'root' })
export class LoteService {
  constructor(private api: ApiService) {}

  crear(payload: LoteCreate) {
    return this.api.post<Lote>('/lotes', payload);
  }

  actualizar(idLote: number, payload: LoteUpdate) {
    return this.api.patch<Lote>(`/lotes/${idLote}`, payload);
  }

  subirImagen(formData: FormData) {
    return this.api.post<{ url: string }>('/uploads/imagen-lote', formData);
  }

  agregarImagen(idLote: number, url: string, esPortada: boolean, orden: number) {
    return this.api.post<LoteImagen>(`/lotes/${idLote}/imagenes`, {
      url,
      es_portada: esPortada,
      orden,
    });
  }

  eliminarImagen(idLote: number, idImagen: number) {
    return this.api.delete(`/lotes/${idLote}/imagenes/${idImagen}`);
  }
}