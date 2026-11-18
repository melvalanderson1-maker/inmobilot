import { Injectable, inject } from '@angular/core';
import { AuthService } from './auth.service';

interface Envoltorio<T> {
  guardadoEn: number;
  datos: T;
}

@Injectable({ providedIn: 'root' })
export class BorradorService {
  private auth = inject(AuthService);
  private readonly TTL_MS = 7 * 24 * 60 * 60 * 1000;
  private timers = new Map<string, ReturnType<typeof setTimeout>>();

  private clave(nombre: string): string {
    return `borrador:${this.auth.usuario()?.id ?? 'anon'}:${nombre}`;
  }

  /** Guarda con retraso (varios cambios seguidos = una sola escritura) */
  guardar(nombre: string, datos: unknown, esperaMs = 400): void {
    const k = this.clave(nombre);
    clearTimeout(this.timers.get(k));
    this.timers.set(
      k,
      setTimeout(() => {
        this.timers.delete(k);
        this.escribir(k, datos);
      }, esperaMs),
    );
  }

  guardarYa(nombre: string, datos: unknown): void {
    const k = this.clave(nombre);
    clearTimeout(this.timers.get(k));
    this.timers.delete(k);
    this.escribir(k, datos);
  }

  private escribir(k: string, datos: unknown): void {
    try {
      const env: Envoltorio<unknown> = { guardadoEn: Date.now(), datos };
      localStorage.setItem(k, JSON.stringify(env));
    } catch {
      /* sin almacenamiento o lleno: se ignora */
    }
  }

  leer<T>(nombre: string): T | null {
    try {
      const crudo = localStorage.getItem(this.clave(nombre));
      if (!crudo) return null;
      const env = JSON.parse(crudo) as Envoltorio<T>;
      if (Date.now() - env.guardadoEn > this.TTL_MS) {
        localStorage.removeItem(this.clave(nombre));
        return null;
      }
      return env.datos;
    } catch {
      return null;
    }
  }

  /** Cancela cualquier guardado pendiente y borra el borrador */
  borrar(nombre: string): void {
    const k = this.clave(nombre);
    clearTimeout(this.timers.get(k));
    this.timers.delete(k);
    try {
      localStorage.removeItem(k);
    } catch {
      /* nada */
    }
  }
}