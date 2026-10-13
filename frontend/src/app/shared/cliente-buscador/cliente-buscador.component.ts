import { CommonModule } from '@angular/common';
import { Component, ElementRef, EventEmitter, HostListener, Input, Output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Subject, of } from 'rxjs';
import { catchError, debounceTime, distinctUntilChanged, switchMap } from 'rxjs/operators';

import { ClienteService } from '../../core/services/cliente.service';
import { Cliente } from '../../core/models';

@Component({
  selector: 'app-cliente-buscador',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './cliente-buscador.component.html',
  styleUrl: './cliente-buscador.component.css',
})
export class ClienteBuscadorComponent {
  @Input() excluirIds: number[] = [];
  @Input() placeholder = 'Buscar por DNI, celular, nombre o apellido';
  @Output() seleccionado = new EventEmitter<Cliente>();
  @Output() crearNuevo = new EventEmitter<string>();

  texto = '';
  resultados = signal<Cliente[]>([]);
  buscando = signal(false);
  abierto = signal(false);

  private entrada$ = new Subject<string>();

  constructor(private clienteService: ClienteService, private el: ElementRef<HTMLElement>) {
    this.entrada$
      .pipe(
        debounceTime(300),
        distinctUntilChanged(),
        switchMap((t) => {
          if (t.length < 2) {
            return of([] as Cliente[]);
          }
          this.buscando.set(true);
          return this.clienteService
            .listar({ busqueda: t, activo: true, limite: 8 })
            .pipe(catchError(() => of([] as Cliente[])));
        })
      )
      .subscribe((lista) => {
        this.resultados.set(lista.filter((c) => !this.excluirIds.includes(c.id)));
        this.buscando.set(false);
      });
  }

  onTexto(valor: string): void {
    this.texto = valor;
    this.abierto.set(true);
    this.entrada$.next(valor.trim());
  }

  elegir(c: Cliente): void {
    this.seleccionado.emit(c);
    this.texto = '';
    this.resultados.set([]);
    this.abierto.set(false);
    this.entrada$.next('');
  }

  crear(): void {
    this.crearNuevo.emit(this.texto.trim());
    this.abierto.set(false);
  }

  nombre(c: Cliente): string {
    return c.tipo_persona === 'juridica' ? c.razon_social || c.nombres : `${c.nombres} ${c.apellidos}`;
  }

  documento(c: Cliente): string {
    return c.tipo_persona === 'juridica' ? `RUC ${c.ruc ?? c.numero_documento}` : `${c.tipo_documento} ${c.numero_documento}`;
  }

  @HostListener('document:click', ['$event'])
  onClickFuera(evento: Event): void {
    if (!this.el.nativeElement.contains(evento.target as Node)) {
      this.abierto.set(false);
    }
  }
}