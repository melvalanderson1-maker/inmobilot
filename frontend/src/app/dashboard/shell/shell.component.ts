import { CommonModule } from '@angular/common';
import { Component, OnDestroy, OnInit, signal } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';

import { AuthService } from '../../core/services/auth.service';
import { ApiService } from '../../core/services/api.service';
import { SocketService } from '../../core/services/socket.service';
import { Notificacion } from '../../core/models';
import { ToastContainerComponent } from '../../shared/toast/toast-container.component';

@Component({
  selector: 'app-shell',
  standalone: true,
  imports: [CommonModule, RouterLink, RouterLinkActive, RouterOutlet, ToastContainerComponent],
  templateUrl: './shell.component.html',
  styleUrl: './shell.component.css',
})
export class ShellComponent implements OnInit, OnDestroy {
  notificaciones = signal<Notificacion[]>([]);
  panelNotifAbierto = signal(false);

  constructor(
    public auth: AuthService,
    private api: ApiService,
    private socket: SocketService
  ) {}

  get modulos() {
    return this.auth.usuario()?.modulos ?? [];
  }

  get noLeidas(): number {
    return this.notificaciones().filter((n) => !n.leido).length;
  }

  ngOnInit(): void {
    this.cargarNotificaciones();
    this.socket.conectar();
    this.socket.onEvento.subscribe((evento) => {
      if (evento.evento === 'notificacion:nueva') {
        this.cargarNotificaciones();
      }
    });
  }

  ngOnDestroy(): void {
    this.socket.desconectar();
  }

  cargarNotificaciones(): void {
    this.api.get<Notificacion[]>('/notificaciones', { solo_no_leidas: false }).subscribe((res) => {
      this.notificaciones.set(res);
    });
  }

  toggleNotificaciones(): void {
    this.panelNotifAbierto.update((v) => !v);
  }

  marcarLeido(n: Notificacion): void {
    if (n.leido) return;
    this.api.patch<Notificacion>(`/notificaciones/${n.id}/leido`, {}).subscribe(() => {
      this.cargarNotificaciones();
    });
  }

  cerrarSesion(): void {
    this.auth.logout();
  }
}
