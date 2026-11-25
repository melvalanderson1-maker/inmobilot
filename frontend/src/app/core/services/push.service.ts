import { Injectable, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import { ApiService } from './api.service';

const CLAVE_PREF = 'inmobilot-push';

@Injectable({ providedIn: 'root' })
export class PushService {
  readonly soportado =
    typeof window !== 'undefined' && 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window;
  readonly activo = signal(false);
  readonly bloqueado = signal(false);
  readonly trabajando = signal(false);

  constructor(private api: ApiService) {}

  /** Al entrar: si el usuario ya dio permiso y no lo apagó, deja la suscripción ligada a su cuenta */
  async sincronizar(): Promise<void> {
    if (!this.soportado) return;
    this.bloqueado.set(Notification.permission === 'denied');
    if (Notification.permission !== 'granted' || this.preferenciaApagada()) {
      this.activo.set(false);
      return;
    }
    try {
      await this.suscribir();
    } catch {
      this.activo.set(false);
    }
  }

  async alternar(): Promise<void> {
    if (this.activo()) await this.desactivar(true);
    else await this.activar();
  }

  async activar(): Promise<void> {
    if (!this.soportado) return;
    this.trabajando.set(true);
    try {
      const permiso = await Notification.requestPermission();
      this.bloqueado.set(permiso === 'denied');
      if (permiso !== 'granted') return;
      try { localStorage.removeItem(CLAVE_PREF); } catch {}
      await this.suscribir();
    } finally {
      this.trabajando.set(false);
    }
  }

  /** manual = el usuario lo apagó; false = solo al cerrar sesión (la preferencia no cambia) */
  async desactivar(manual = true): Promise<void> {
    if (!this.soportado) return;
    try {
      const reg = await navigator.serviceWorker.getRegistration('/sw-push.js');
      const sub = await reg?.pushManager.getSubscription();
      if (sub) {
        await firstValueFrom(this.api.post<unknown>('/push/desuscribir', { endpoint: sub.endpoint }));
        await sub.unsubscribe();
      }
    } catch {}
    if (manual) {
      try { localStorage.setItem(CLAVE_PREF, '0'); } catch {}
    }
    this.activo.set(false);
  }

  private preferenciaApagada(): boolean {
    try { return localStorage.getItem(CLAVE_PREF) === '0'; } catch { return false; }
  }

  private async suscribir(): Promise<void> {
    const reg = await navigator.serviceWorker.register('/sw-push.js');
    await navigator.serviceWorker.ready;
    let sub = await reg.pushManager.getSubscription();
    if (!sub) {
      const { clave } = await firstValueFrom(this.api.get<{ clave: string }>('/push/clave-publica'));
      if (!clave) throw new Error('Falta la clave VAPID en el servidor');
      sub = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: this.aBytes(clave) as unknown as BufferSource,
      });
    }
    await firstValueFrom(this.api.post<unknown>('/push/suscribir', sub.toJSON()));
    this.activo.set(true);
  }

  private aBytes(base64Url: string): Uint8Array {
    const relleno = '='.repeat((4 - (base64Url.length % 4)) % 4);
    const b64 = (base64Url + relleno).replace(/-/g, '+').replace(/_/g, '/');
    const bin = atob(b64);
    return Uint8Array.from(bin, (c) => c.charCodeAt(0));
  }
}