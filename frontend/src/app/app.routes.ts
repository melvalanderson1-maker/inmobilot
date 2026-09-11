import { Routes } from '@angular/router';

import { authGuard } from './core/guards/auth.guard';
import { moduloGuard } from './core/guards/modulo.guard';

export const routes: Routes = [
  { path: '', redirectTo: 'catalogo/gruselva/oro-verde', pathMatch: 'full' },

  {
    path: 'catalogo/:empresaSlug/:proyectoSlug',
    loadComponent: () =>
      import('./public/catalogo/catalogo.component').then((c) => c.CatalogoComponent),
  },

  {
    path: 'login',
    loadComponent: () => import('./auth/login/login.component').then((c) => c.LoginComponent),
  },

  {
    path: 'dashboard',
    canActivate: [authGuard],
    loadComponent: () =>
      import('./dashboard/shell/shell.component').then((c) => c.ShellComponent),
    children: [
      { path: '', redirectTo: 'lotes', pathMatch: 'full' },
      {
        path: 'proyectos',
        canActivate: [moduloGuard('proyectos')],
        loadComponent: () =>
          import('./dashboard/proyectos/proyectos-list.component').then((c) => c.ProyectosListComponent),
      },
      {
        path: 'lotes',
        canActivate: [moduloGuard('lotes')],
        loadComponent: () =>
          import('./dashboard/lotes/lotes-list.component').then((c) => c.LotesListComponent),
      },
      {
        path: 'leads',
        canActivate: [moduloGuard('leads')],
        loadComponent: () =>
          import('./dashboard/leads/leads-list.component').then((c) => c.LeadsListComponent),
      },
      {
        path: 'usuarios',
        canActivate: [moduloGuard('usuarios')],
        loadComponent: () =>
          import('./dashboard/usuarios/usuarios-list.component').then((c) => c.UsuariosListComponent),
      },
      {
        path: 'contratos',
        canActivate: [moduloGuard('contratos')],
        loadComponent: () =>
          import('./dashboard/contratos/contratos-list.component').then((c) => c.ContratosListComponent),
      },
      // Pendiente: contratos, pagos, documentos (ver README)
    ],
  },

  { path: '**', redirectTo: '' },
];
