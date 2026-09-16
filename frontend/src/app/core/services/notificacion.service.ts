import { Injectable } from '@angular/core';
import { ApiService } from './api.service';
import { Notificacion } from '../models';

@Injectable({ providedIn: 'root' })
export class NotificacionService {
  constructor(private api: ApiService) {}

  listar(soloNoLeidas = false) {
    return this.api.get<Notificacion[]>('/notificaciones', { solo_no_leidas: soloNoLeidas });
  }

  marcarLeido(idNotificacion: number) {
    return this.api.patch<Notificacion>(`/notificaciones/${idNotificacion}/leido`, {});
  }
}