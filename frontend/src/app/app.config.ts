import { ApplicationConfig, APP_INITIALIZER } from '@angular/core';
import { provideRouter } from '@angular/router';
import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { provideAnimations } from '@angular/platform-browser/animations';

import { routes } from './app.routes';
import { jwtInterceptor } from './core/interceptors/jwt.interceptor';
import { ConfigService } from './core/services/config.service';
import { TenantService } from './core/services/tenant.service';

export function inicializarApp(configService: ConfigService, tenantService: TenantService) {
  return async () => {
    await configService.cargar();
    await tenantService.cargar();
  };
}

export const appConfig: ApplicationConfig = {
  providers: [
    provideRouter(routes),
    provideHttpClient(withInterceptors([jwtInterceptor])),
    provideAnimations(),
    {
      provide: APP_INITIALIZER,
      useFactory: inicializarApp,
      deps: [ConfigService, TenantService],
      multi: true,
    },
  ],
};