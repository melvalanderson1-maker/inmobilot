import { Injectable, OnDestroy } from '@angular/core';
import { Subject } from 'rxjs';
import { io, Socket } from 'socket.io-client';

import { environment } from '../../../environments/environment';
import { AuthService } from './auth.service';

export interface EventoSocket<T = unknown> {
  evento: string;
  data: T;
}

@Injectable({ providedIn: 'root' })
export class SocketService implements OnDestroy {
  private socket: Socket | null = null;
  private eventos$ = new Subject<EventoSocket>();

  readonly onEvento = this.eventos$.asObservable();

  constructor(private auth: AuthService) {}

  conectar(): void {
    const token = this.auth.token();
    if (!token || this.socket?.connected) return;

    this.socket = io(environment.socketUrl, {
      path: '/socket.io',
      auth: { token },
      transports: ['websocket'],
    });

    this.escucharEventos();
  }

  conectarPublico(idProyecto: number): void {
    if (this.socket?.connected) return;

    this.socket = io(environment.socketUrl, {
      path: '/socket.io',
      transports: ['websocket'],
    });

    this.socket.on('connect', () => {
      this.socket?.emit('unirse_proyecto_publico', { id_proyecto: idProyecto });
    });

    this.escucharEventos();
  }

  private escucharEventos(): void {
    if (!this.socket) return;

    const eventosEscuchados = [
      'lote:nuevo',
      'lote:cambio_estado',
      'lote:actualizado',
      'lead:nuevo',
      'cuota:vence_hoy',
      'notificacion:nueva',
      'usuario:proyectos_actualizados',
      'contrato:nuevo',
      'contrato:pago_registrado',
    ];

    for (const evento of eventosEscuchados) {
      this.socket.on(evento, (data: unknown) => this.eventos$.next({ evento, data }));
    }
  }

  desconectar(): void {
    this.socket?.disconnect();
    this.socket = null;
  }

  ngOnDestroy(): void {
    this.desconectar();
  }
}
