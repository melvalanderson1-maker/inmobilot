import { Routes } from '@angular/router';

import { authGuard } from './core/guards/auth.guard';
import { moduloGuard } from './core/guards/modulo.guard';
import { homeRedirectGuard } from './core/guards/home-redirect.guard';

export const routes: Routes = [
  {
    path: '',
    loadComponent: () =>
      import('./public/catalogo/catalogo.component').then((c) => c.CatalogoComponent),
  },

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
      { path: '', canActivate: [homeRedirectGuard], redirectTo: 'lotes', pathMatch: 'full' },
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
      {
        path: 'separaciones',
        canActivate: [moduloGuard('separaciones')],
        loadComponent: () =>
          import('./dashboard/separaciones/separaciones-list.component').then((c) => c.SeparacionesListComponent),
      },
      {
        path: 'separaciones/nueva',
        canActivate: [moduloGuard('separaciones')],
        loadComponent: () =>
          import('./dashboard/separaciones/separacion-form.component').then((c) => c.SeparacionFormComponent),
      },
      {
        path: 'separaciones/:id',
        canActivate: [moduloGuard('separaciones')],
        loadComponent: () =>
          import('./dashboard/separaciones/separacion-detalle.component').then((c) => c.SeparacionDetalleComponent),
      },
      {
        path: 'clientes',
        canActivate: [moduloGuard('clientes')],
        loadComponent: () =>
          import('./dashboard/clientes/clientes-list.component').then((c) => c.ClientesListComponent),
      },
      {
        path: 'clientes/nuevo',
        canActivate: [moduloGuard('clientes')],
        loadComponent: () =>
          import('./dashboard/clientes/cliente-form.component').then((c) => c.ClienteFormComponent),
      },
      {
        path: 'clientes/:id/editar',
        canActivate: [moduloGuard('clientes')],
        loadComponent: () =>
          import('./dashboard/clientes/cliente-form.component').then((c) => c.ClienteFormComponent),
      },
      {
        path: 'clientes/:id',
        canActivate: [moduloGuard('clientes')],
        loadComponent: () =>
          import('./dashboard/clientes/cliente-detalle.component').then((c) => c.ClienteDetalleComponent),
      },
      // Pendiente: pagos, documentos (ver README)
    ],
  },

  { path: '**', redirectTo: '' },
];
