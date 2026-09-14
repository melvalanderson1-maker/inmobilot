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
  colapsado = signal(false);
  mostrarModalLogout = signal(false);

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

  get inicialesUsuario(): string {
    const nombre = this.auth.usuario()?.nombre ?? '';
    const partes = nombre.trim().split(' ').filter(Boolean);
    if (partes.length === 0) return '?';
    if (partes.length === 1) return partes[0].charAt(0).toUpperCase();
    return (partes[0].charAt(0) + partes[1].charAt(0)).toUpperCase();
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

  toggleSidebar(): void {
    this.colapsado.update((v) => !v);
  }

  marcarLeido(n: Notificacion): void {
    if (n.leido) return;
    this.api.patch<Notificacion>(`/notificaciones/${n.id}/leido`, {}).subscribe(() => {
      this.cargarNotificaciones();
    });
  }

  abrirModalLogout(): void {
    this.mostrarModalLogout.set(true);
  }

  cancelarLogout(): void {
    this.mostrarModalLogout.set(false);
  }

  confirmarLogout(): void {
    this.mostrarModalLogout.set(false);
    this.auth.logout();
  }

  tipoIcono(nombre: string): string {
    const n = (nombre ?? '').toLowerCase();

    if (n.includes('dashboard') || n.includes('inicio') || n.includes('panel')) return 'dashboard';
    if (n.includes('lote')) return 'lotes';
    if (n.includes('contrato')) return 'contratos';
    if (n.includes('cliente')) return 'clientes';
    if (n.includes('usuario') || n.includes('equipo')) return 'usuarios';
    if (n.includes('proyecto')) return 'proyectos';
    if (n.includes('pago') || n.includes('cobranza') || n.includes('cuota')) return 'pagos';
    if (n.includes('reporte') || n.includes('kpi') || n.includes('meta')) return 'reportes';
    if (n.includes('lead') || n.includes('seguimiento')) return 'leads';

    return 'default';
  }
}