import { Injectable, signal } from '@angular/core';

@Injectable({ providedIn: 'root' })
export class LoaderService {
  visible = signal(false);
  mensaje = signal('Cargando...');

  show(mensaje = 'Cargando...'): void {
    this.mensaje.set(mensaje);
    this.visible.set(true);
  }

  hide(): void {
    this.visible.set(false);
  }
}