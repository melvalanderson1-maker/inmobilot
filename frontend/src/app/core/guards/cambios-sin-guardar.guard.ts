import { CanDeactivateFn } from '@angular/router';

export interface ConCambiosPendientes {
  tieneCambiosSinGuardar(): boolean;
}

export const cambiosSinGuardarGuard: CanDeactivateFn<ConCambiosPendientes> = (componente) =>
  !componente.tieneCambiosSinGuardar() ||
  confirm('Tienes cambios sin guardar. Si sales, se conserva un borrador en este equipo. ¿Salir de todas formas?');