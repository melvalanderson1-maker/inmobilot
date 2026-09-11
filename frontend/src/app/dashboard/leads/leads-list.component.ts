import { CommonModule } from '@angular/common';
import { Component, OnInit, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { ApiService } from '../../core/services/api.service';
import { EstadoLead, Lead, LeadSeguimiento, Proyecto } from '../../core/models';

@Component({
  selector: 'app-leads-list',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './leads-list.component.html',
  styleUrl: './leads-list.component.css',
})
export class LeadsListComponent implements OnInit {
  proyectos = signal<Proyecto[]>([]);
  leads = signal<Lead[]>([]);
  cargando = signal(false);

  idProyectoSeleccionado: number | null = null;
  filtroEstado = '';

  leadSeleccionado = signal<Lead | null>(null);
  seguimientos = signal<LeadSeguimiento[]>([]);
  nuevaNota = '';

  constructor(private api: ApiService) {}

  ngOnInit(): void {
    this.api.get<Proyecto[]>('/proyectos').subscribe((proyectos) => {
      this.proyectos.set(proyectos);
      if (proyectos.length > 0) {
        this.idProyectoSeleccionado = proyectos[0].id;
        this.cargarLeads();
      }
    });
  }

  cargarLeads(): void {
    if (!this.idProyectoSeleccionado) return;
    this.cargando.set(true);
    this.api
      .get<Lead[]>('/leads', {
        id_proyecto: this.idProyectoSeleccionado,
        estado: this.filtroEstado || undefined,
      })
      .subscribe({
        next: (res) => {
          this.leads.set(res);
          this.cargando.set(false);
        },
        error: () => this.cargando.set(false),
      });
  }

  abrirLead(lead: Lead): void {
    this.leadSeleccionado.set(lead);
    this.nuevaNota = '';
    this.api.get<LeadSeguimiento[]>(`/leads/${lead.id}/seguimientos`).subscribe((res) => {
      this.seguimientos.set(res);
    });
  }

  cerrarLead(): void {
    this.leadSeleccionado.set(null);
    this.seguimientos.set([]);
  }

  cambiarEstadoLead(estado: EstadoLead): void {
    const lead = this.leadSeleccionado();
    if (!lead) return;
    this.api.patch<Lead>(`/leads/${lead.id}`, { estado }).subscribe((actualizado) => {
      this.leadSeleccionado.set(actualizado);
      this.cargarLeads();
    });
  }

  agregarNota(): void {
    const lead = this.leadSeleccionado();
    if (!lead || !this.nuevaNota.trim()) return;

    this.api
      .post<LeadSeguimiento>(`/leads/${lead.id}/seguimientos`, { nota: this.nuevaNota })
      .subscribe((nueva) => {
        this.seguimientos.update((actuales) => [nueva, ...actuales]);
        this.nuevaNota = '';
        this.cargarLeads();
      });
  }
}
