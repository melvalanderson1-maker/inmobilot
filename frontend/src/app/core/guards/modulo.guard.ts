import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';

import { AuthService } from '../services/auth.service';

/**
 * Uso en las rutas:
 *   { path: 'lotes', canActivate: [moduloGuard('lotes')], ... }
 */
export const moduloGuard = (claveModulo: string): CanActivateFn => {
  return () => {
    const auth = inject(AuthService);
    const router = inject(Router);

    if (!auth.estaLogueado()) {
      router.navigate(['/login']);
      return false;
    }

    if (auth.tieneModulo(claveModulo)) return true;

    router.navigate(['/dashboard']);
    return false;
  };
};
