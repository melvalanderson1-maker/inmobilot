import { Injectable, signal } from '@angular/core';

@Injectable({ providedIn: 'root' })
export class SonidoService {
  private ctx: AudioContext | null = null;
  readonly habilitado = signal(
    typeof localStorage === 'undefined' ? true : localStorage.getItem('sonido_notificaciones') !== 'off'
  );

  constructor() {
    if (typeof window === 'undefined') return;
    // Los navegadores solo permiten audio tras una interacción del usuario: se "desbloquea" con el primer clic o tecla
    const desbloquear = () => {
      this.contexto();
      window.removeEventListener('click', desbloquear);
      window.removeEventListener('keydown', desbloquear);
    };
    window.addEventListener('click', desbloquear);
    window.addEventListener('keydown', desbloquear);
  }

  private contexto(): AudioContext | null {
    if (typeof window === 'undefined') return null;
    if (!this.ctx) {
      const Ctor = window.AudioContext || (window as any).webkitAudioContext;
      if (!Ctor) return null;
      this.ctx = new Ctor();
    }
    if (this.ctx.state === 'suspended') {
      this.ctx.resume();
    }
    return this.ctx;
  }

  reproducir(): void {
    if (!this.habilitado()) return;
    const ctx = this.contexto();
    if (!ctx) return;

    const ahora = ctx.currentTime;
    const notas: [number, number][] = [
      [880, 0],
      [1320, 0.16],
    ];
    for (const [frecuencia, desfase] of notas) {
      const osc = ctx.createOscillator();
      const ganancia = ctx.createGain();
      osc.type = 'sine';
      osc.frequency.value = frecuencia;
      ganancia.gain.setValueAtTime(0.0001, ahora + desfase);
      ganancia.gain.exponentialRampToValueAtTime(0.25, ahora + desfase + 0.02);
      ganancia.gain.exponentialRampToValueAtTime(0.0001, ahora + desfase + 0.35);
      osc.connect(ganancia).connect(ctx.destination);
      osc.start(ahora + desfase);
      osc.stop(ahora + desfase + 0.4);
    }
  }

  alternar(): void {
    const nuevo = !this.habilitado();
    this.habilitado.set(nuevo);
    localStorage.setItem('sonido_notificaciones', nuevo ? 'on' : 'off');
    if (nuevo) this.reproducir();
  }
}