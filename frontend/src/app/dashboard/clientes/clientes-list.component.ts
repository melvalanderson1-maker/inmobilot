import { CommonModule } from '@angular/common';
import { Component, OnInit, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';

import { ClienteService } from '../../core/services/cliente.service';
import { Cliente } from '../../core/models';

@Component({
  selector: 'app-clientes-list',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './clientes-list.component.html',
  styleUrl: './clientes-list.component.css',
})
export class ClientesListComponent implements OnInit {
  clientes = signal<Cliente[]>([]);
  cargando = signal(false);
  busqueda = '';
  filtroTipo: 'todos' | 'natural' | 'juridica' = 'todos';

  constructor(private clienteService: ClienteService, private router: Router) {}

  ngOnInit(): void {
    this.cargar();
  }

  cargar(): void {
    this.cargando.set(true);
    const filtros: { busqueda?: string; tipo_persona?: string } = {};
    if (this.busqueda.trim()) filtros.busqueda = this.busqueda.trim();
    if (this.filtroTipo !== 'todos') filtros.tipo_persona = this.filtroTipo;

    this.clienteService.listar(filtros).subscribe({
      next: (res) => {
        this.clientes.set(res);
        this.cargando.set(false);
      },
      error: () => this.cargando.set(false),
    });
  }

  nombreCompleto(c: Cliente): string {
    return c.tipo_persona === 'juridica' ? c.razon_social || c.nombres : `${c.nombres} ${c.apellidos}`;
  }

  irANuevo(): void {
    this.router.navigate(['/dashboard/clientes/nuevo']);
  }

  irADetalle(c: Cliente): void {
    this.router.navigate(['/dashboard/clientes', c.id]);
  }
}