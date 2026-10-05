import { CommonModule } from '@angular/common';
import { Component, OnInit, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { ApiService } from '../../core/services/api.service';
import { ToastService } from '../../core/services/toast.service';
import { EmpresaConfig } from '../../core/models';

@Component({
  selector: 'app-empresa-config',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './empresa-config.component.html',
  styleUrl: './empresa-config.component.css',
})
export class EmpresaConfigComponent implements OnInit {
  cargando = signal(false);
  guardando = signal(false);

  form: EmpresaConfig = {};

  constructor(private api: ApiService, private toastService: ToastService) {}

  ngOnInit(): void {
    this.cargando.set(true);
    this.api.get<EmpresaConfig>('/empresa/configuracion-legal').subscribe({
      next: (res) => {
        this.form = res;
        this.cargando.set(false);
      },
      error: () => this.cargando.set(false),
    });
  }

  guardar(): void {
    this.guardando.set(true);
    this.api.patch<EmpresaConfig>('/empresa/configuracion-legal', this.form).subscribe({
      next: () => {
        this.guardando.set(false);
        this.toastService.exito('Configuración legal actualizada');
      },
      error: (err) => {
        this.guardando.set(false);
        this.toastService.error(err?.error?.detail ?? 'No se pudo guardar');
      },
    });
  }
}