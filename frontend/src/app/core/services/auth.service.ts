import { Injectable, computed, signal } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Router } from '@angular/router';
import { Observable, tap } from 'rxjs';

import { ConfigService } from './config.service';
import { TokenResponse, UsuarioMe } from '../models';

const TOKEN_KEY = 'inmobilot_token';
const USER_KEY = 'inmobilot_user';

@Injectable({ providedIn: 'root' })
export class AuthService {
  private tokenSignal = signal<string | null>(localStorage.getItem(TOKEN_KEY));
  private usuarioSignal = signal<UsuarioMe | null>(this.readStoredUser());

  readonly token = computed(() => this.tokenSignal());
  readonly usuario = computed(() => this.usuarioSignal());
  readonly estaLogueado = computed(() => !!this.tokenSignal());

  readonly modulosClaves = computed(
    () => new Set(this.usuarioSignal()?.modulos.map((m) => m.clave) ?? [])
  );

  constructor(private http: HttpClient, private router: Router, private cfg: ConfigService) {}

  private readStoredUser(): UsuarioMe | null {
    const raw = localStorage.getItem(USER_KEY);
    return raw ? (JSON.parse(raw) as UsuarioMe) : null;
  }

  login(correo: string, password: string): Observable<TokenResponse> {
    return this.http
      .post<TokenResponse>(`${this.cfg.apiUrl()}/auth/login-json`, { correo, password })
      .pipe(
        tap((res) => {
          localStorage.setItem(TOKEN_KEY, res.access_token);
          localStorage.setItem(USER_KEY, JSON.stringify(res.usuario));
          this.tokenSignal.set(res.access_token);
          this.usuarioSignal.set(res.usuario);
        })
      );
  }

  logout(): void {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
    this.tokenSignal.set(null);
    this.usuarioSignal.set(null);
    this.router.navigate(['/login']);
  }

  tieneModulo(clave: string): boolean {
    if (this.usuarioSignal()?.rol.clave === 'admin') return true;
    return this.modulosClaves().has(clave);
  }
}
