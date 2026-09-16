import { Injectable, signal } from '@angular/core';

interface ConfirmState {
  visible: boolean;
  titulo: string;
  mensaje: string;
  resolver?: (valor: boolean) => void;
}

@Injectable({ providedIn: 'root' })
export class ConfirmModalService {
  estado = signal<ConfirmState>({ visible: false, titulo: '', mensaje: '' });

  confirm(titulo: string, mensaje: string): Promise<boolean> {
    return new Promise((resolve) => {
      this.estado.set({ visible: true, titulo, mensaje, resolver: resolve });
    });
  }

  responder(valor: boolean): void {
    this.estado().resolver?.(valor);
    this.estado.set({ visible: false, titulo: '', mensaje: '' });
  }
}