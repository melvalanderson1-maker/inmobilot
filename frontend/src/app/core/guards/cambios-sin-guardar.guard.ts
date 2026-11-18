import { CanDeactivateFn } from '@angular/router';

export interface ConCambiosPendientes {
  tieneCambiosSinGuardar(): boolean;
  /** Abre el modal de salida y responde true si se puede salir, false si se queda */
  confirmarSalidaGuard?(): Promise<boolean>;
}

export const cambiosSinGuardarGuard: CanDeactivateFn<ConCambiosPendientes> = (componente) => {
  if (!componente.tieneCambiosSinGuardar()) return true;

  // Si el componente tiene su propio modal, se usa ese
  if (componente.confirmarSalidaGuard) return componente.confirmarSalidaGuard();

  // Respaldo para otros componentes que no tengan modal propio
  return confirm('Tienes cambios sin guardar. Si sales, se conserva un borrador en este equipo. ¿Salir de todas formas?');
};