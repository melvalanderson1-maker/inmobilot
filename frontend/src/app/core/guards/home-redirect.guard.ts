import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';

import { AuthService } from '../services/auth.service';

export const homeRedirectGuard: CanActivateFn = () => {
  const auth = inject(AuthService);
  const router = inject(Router);

  const destino = auth.primerModuloDisponible();
  if (destino) {
    router.navigate(['/dashboard', destino]);
  } else {
    auth.logout();
  }
  return false;
};