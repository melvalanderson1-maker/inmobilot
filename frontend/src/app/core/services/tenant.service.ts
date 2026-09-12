import { Injectable, signal } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { ConfigService } from './config.service';
import { calcularColorTexto } from '../utils/contraste';

export interface TenantConfig {
  nombre: string;
  slug: string;
  logo_url: string;
  mascota_url: string;
  hero_url: string;
  color_primario: string;
  color_secundario: string;
  whatsapp: string;
  ubicacion: string;
  correo_contacto: string;
}


@Injectable({ providedIn: 'root' })
export class TenantService {
  config = signal<TenantConfig | null>(null);

  constructor(
    private http: HttpClient,
    private cfg: ConfigService
  ) {}

  cargar(): Promise<void> {
    return new Promise((resolve) => {
      this.http
        .get<TenantConfig>(`${this.cfg.apiUrl()}/config/tenant`)
        .subscribe({
          next: (cfg) => {
            this.config.set(cfg);
            this.aplicarTema(cfg);
            resolve();
          },
          error: () => resolve(),
        });
    });
  }

  private aplicarTema(cfg: TenantConfig): void {
    document.documentElement.style.setProperty(
      '--color-primario',
      cfg.color_primario
    );

    document.documentElement.style.setProperty(
      '--color-secundario',
      cfg.color_secundario
    );

    // Texto siempre legible encima de cada color, sin importar
    // qué tonos elija cada inmobiliaria.
    document.documentElement.style.setProperty(
      '--texto-sobre-primario',
      calcularColorTexto(cfg.color_primario)
    );
    document.documentElement.style.setProperty(
      '--texto-sobre-secundario',
      calcularColorTexto(cfg.color_secundario)
    );

    document.title = cfg.nombre;
  }

  logoUrl(): string {
    const url = this.config()?.logo_url ?? '';

    if (url.startsWith('http')) {
      return url;
    }

    return `${this.cfg.apiUrl()}${url}`;
  }
}