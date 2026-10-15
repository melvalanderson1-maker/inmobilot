import { CommonModule } from '@angular/common';
import { Component, HostListener, OnDestroy, OnInit, signal } from '@angular/core';
import { Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';

import { AuthService } from '../../core/services/auth.service';
import { ApiService } from '../../core/services/api.service';
import { SocketService } from '../../core/services/socket.service';
import { SonidoService } from '../../core/services/sonido.service';
import { Notificacion } from '../../core/models';
import { ToastContainerComponent } from '../../shared/toast/toast-container.component';
import { LoaderComponent } from '../../shared/loader/loader.component';
import { ConfirmModalComponent } from '../../shared/confirm-modal/confirm-modal.component';

type TemaApp = 'oscuro' | 'claro';

@Component({
  selector: 'app-shell',
  standalone: true,
  imports: [CommonModule, RouterLink, RouterLinkActive, RouterOutlet, ToastContainerComponent, LoaderComponent, ConfirmModalComponent],
  templateUrl: './shell.component.html',
  styleUrl: './shell.component.css',
})
export class ShellComponent implements OnInit, OnDestroy {
  notificaciones = signal<Notificacion[]>([]);
  panelNotifAbierto = signal(false);
  colapsado = signal(false);
  mostrarModalLogout = signal(false);
  menuMovilAbierto = signal(false);
  tema = signal<TemaApp>(this.temaInicial());
  private idsConocidos = new Set<number>();
  private primeraCarga = true;

  constructor(
    public auth: AuthService,
    private api: ApiService,
    private socket: SocketService,
    public sonido: SonidoService,
    private router: Router
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
    this.bloquearScroll(false);
    this.socket.desconectar(true);
  }

  // ===== TEMA OSCURO / CLARO =====

  private temaInicial(): TemaApp {
    let guardado: string | null = null;
    try {
      guardado = localStorage.getItem('inmobilot-tema');
    } catch {}
    const tema: TemaApp = guardado === 'claro' ? 'claro' : 'oscuro';
    if (typeof document !== 'undefined') {
      document.documentElement.setAttribute('data-tema', tema);
    }
    return tema;
  }

  alternarTema(): void {
    const nuevo: TemaApp = this.tema() === 'oscuro' ? 'claro' : 'oscuro';
    this.tema.set(nuevo);
    document.documentElement.setAttribute('data-tema', nuevo);
    try {
      localStorage.setItem('inmobilot-tema', nuevo);
    } catch {}
  }

  // ===== NOTIFICACIONES =====

  cargarNotificaciones(): void {
    this.api.get<Notificacion[]>('/notificaciones', { solo_no_leidas: false }).subscribe((res) => {
      const miId = this.auth.usuario()?.id;
      if (!this.primeraCarga) {
        // Suena solo con notificaciones nuevas sin leer y que no provocó el propio usuario
        const nuevas = res.filter(
          (n) =>
            !n.leido &&
            !this.idsConocidos.has(n.id) &&
            (n.data?.['id_usuario_accion'] as number | undefined) !== miId
        );
        if (nuevas.length > 0) this.sonido.reproducir();
      }
      res.forEach((n) => this.idsConocidos.add(n.id));
      this.primeraCarga = false;
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

  /** Al hacer clic en una notificación: se marca leída y te lleva a donde corresponde. */
  abrirNotificacion(n: Notificacion): void {
    this.marcarLeido(n);
    const d = (n.data ?? {}) as Record<string, any>;
    if (d['id_pago']) {
      this.panelNotifAbierto.set(false);
      this.router.navigate(['/dashboard/pagos']);
    } else if (d['id_separacion']) {
      this.panelNotifAbierto.set(false);
      this.router.navigate(['/dashboard/separaciones', d['id_separacion']]);
    } else if (d['id_venta']) {
      this.panelNotifAbierto.set(false);
      this.router.navigate(['/dashboard/contratos/venta', d['id_venta']]);
    }
  }

  // ===== SIDEBAR / MENÚ MÓVIL =====

  toggleSidebar(): void {
    this.colapsado.update((v) => !v);
  }

  toggleMenuMovil(): void {
    this.colapsado.set(false);
    this.menuMovilAbierto.update((v) => !v);
    this.bloquearScroll(this.menuMovilAbierto());
  }

  cerrarMenuMovil(): void {
    this.menuMovilAbierto.set(false);
    this.bloquearScroll(false);
  }

  /** Evita que el fondo se desplace mientras el menú móvil está abierto. */
  private bloquearScroll(bloquear: boolean): void {
    if (typeof document === 'undefined') return;
    document.body.style.overflow = bloquear ? 'hidden' : '';
  }

  /** Si agrandas la ventana (rotar tablet, redimensionar), cierra el menú móvil. */
  @HostListener('window:resize')
  onResize(): void {
    if (window.innerWidth > 900 && this.menuMovilAbierto()) {
      this.cerrarMenuMovil();
    }
  }

  @HostListener('document:keydown.escape')
  onEscape(): void {
    if (this.panelNotifAbierto()) {
      this.panelNotifAbierto.set(false);
      return;
    }
    if (this.mostrarModalLogout()) {
      this.cancelarLogout();
      return;
    }
    if (this.menuMovilAbierto()) {
      this.cerrarMenuMovil();
    }
  }

  // ===== LOGOUT =====

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

  // ===== ICONOS =====

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
    if (n.includes('separacion')) return 'separaciones';

    return 'default';
  }
}