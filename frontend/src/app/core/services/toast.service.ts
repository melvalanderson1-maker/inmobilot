import { Injectable, signal } from '@angular/core';

export type TipoToast = 'exito' | 'error' | 'info';

export interface ToastItem {
  id: number;
  tipo: TipoToast;
  titulo: string;
  mensaje?: string;
}

@Injectable({ providedIn: 'root' })
export class ToastService {
  toasts = signal<ToastItem[]>([]);
  private contador = 0;

  private mostrar(tipo: TipoToast, titulo: string, mensaje?: string, duracionMs = 4500): void {
    const id = ++this.contador;
    this.toasts.update((actuales) => [...actuales, { id, tipo, titulo, mensaje }]);
    setTimeout(() => this.cerrar(id), duracionMs);
  }

  exito(titulo: string, mensaje?: string): void {
    this.mostrar('exito', titulo, mensaje);
  }

  error(titulo: string, mensaje?: string): void {
    this.mostrar('error', titulo, mensaje, 6000);
  }

  info(titulo: string, mensaje?: string): void {
    this.mostrar('info', titulo, mensaje);
  }

  cerrar(id: number): void {
    this.toasts.update((actuales) => actuales.filter((t) => t.id !== id));
  }
}