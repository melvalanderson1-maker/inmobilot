import { Injectable, signal } from '@angular/core';
import { HttpClient } from '@angular/common/http';

@Injectable({ providedIn: 'root' })
export class ConfigService {
  apiUrl = signal<string>('http://localhost:8000');

  constructor(private http: HttpClient) {}

  cargar(): Promise<void> {
    return new Promise((resolve) => {
      this.http.get<{ apiUrl: string }>('/env.json').subscribe({
        next: (cfg) => {
          this.apiUrl.set(cfg.apiUrl);
          resolve();
        },
        error: () => resolve(), // si falla, se queda con el valor por defecto
      });
    });
  }
}