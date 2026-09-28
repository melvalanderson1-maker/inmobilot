import { CommonModule } from '@angular/common';
import { Component, OnInit, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';

import { ClienteService } from '../../core/services/cliente.service';
import { ToastService } from '../../core/services/toast.service';
import { ClienteCreate, ClienteUpdate, EstadoCivil, TipoPersona } from '../../core/models';

@Component({
  selector: 'app-cliente-form',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './cliente-form.component.html',
  styleUrl: './cliente-form.component.css',
})
export class ClienteFormComponent implements OnInit {
  idCliente: number | null = null;
  returnTo: string | null = null;
  idProyectoReturn: string | null = null;

  guardando = signal(false);
  cargando = signal(false);
  error = signal<string | null>(null);
  subiendoDni = signal(false);

  form = {
    tipo_persona: 'natural' as TipoPersona,
    tipo_documento: 'DNI',
    numero_documento: '',
    nombres: '',
    apellidos: '',
    correo: '',
    telefono: '',
    direccion: '',
    dni_url: null as string | null,
    fecha_nacimiento: '',
    estado_civil: '' as EstadoCivil | '',
    segundo_contacto_nombre: '',
    segundo_contacto_telefono: '',
    ruc: '',
    razon_social: '',
    representante_legal: '',
  };

  conyuge = {
    nombres: '',
    apellidos: '',
    numero_documento: '',
    telefono: '',
  };

  constructor(
    private clienteService: ClienteService,
    private toastService: ToastService,
    private route: ActivatedRoute,
    private router: Router
  ) {}

  get esEdicion(): boolean {
    return this.idCliente !== null;
  }

  get esCasado(): boolean {
    return this.form.estado_civil === 'casado';
  }

  ngOnInit(): void {
    const idParam = this.route.snapshot.paramMap.get('id');
    this.idCliente = idParam ? Number(idParam) : null;

    this.route.queryParams.subscribe((params) => {
      this.returnTo = params['returnTo'] ?? null;
      this.idProyectoReturn = params['id_proyecto'] ?? null;
      if (params['documento'] && !this.esEdicion) {
        this.form.numero_documento = params['documento'];
      }
    });

    if (this.idCliente) {
      this.cargando.set(true);
      this.clienteService.obtener(this.idCliente).subscribe({
        next: (c) => {
          this.form = {
            tipo_persona: c.tipo_persona,
            tipo_documento: c.tipo_documento,
            numero_documento: c.numero_documento,
            nombres: c.nombres,
            apellidos: c.apellidos,
            correo: c.correo ?? '',
            telefono: c.telefono ?? '',
            direccion: c.direccion ?? '',
            dni_url: c.dni_url ?? null,
            fecha_nacimiento: c.fecha_nacimiento ?? '',
            estado_civil: c.estado_civil ?? '',
            segundo_contacto_nombre: c.segundo_contacto_nombre ?? '',
            segundo_contacto_telefono: c.segundo_contacto_telefono ?? '',
            ruc: c.ruc ?? '',
            razon_social: c.razon_social ?? '',
            representante_legal: c.representante_legal ?? '',
          };
          if (c.conyuge) {
            this.conyuge = {
              nombres: c.conyuge.nombres,
              apellidos: c.conyuge.apellidos,
              numero_documento: c.conyuge.numero_documento,
              telefono: c.conyuge.telefono ?? '',
            };
          }
          this.cargando.set(false);
        },
        error: () => this.cargando.set(false),
      });
    }
  }

  onDniSeleccionado(event: Event): void {
    const input = event.target as HTMLInputElement;
    const archivo = input.files?.[0];
    if (!archivo) return;

    const formData = new FormData();
    formData.append('archivo', archivo);
    this.subiendoDni.set(true);

    this.clienteService.subirArchivo(formData).subscribe({
      next: (res) => {
        this.form.dni_url = res.url;
        this.subiendoDni.set(false);
      },
      error: (err) => {
        this.subiendoDni.set(false);
        this.toastService.error(err?.error?.detail ?? 'No se pudo subir el DNI');
      },
    });
    input.value = '';
  }

  private validar(): string | null {
    if (this.form.tipo_persona === 'juridica') {
      if (!this.form.ruc?.trim() || !this.form.razon_social?.trim() || !this.form.representante_legal?.trim()) {
        return 'RUC, razón social y representante legal son obligatorios';
      }
    } else {
      if (!this.form.nombres.trim() || !this.form.apellidos.trim()) {
        return 'Nombres y apellidos son obligatorios';
      }
      if (this.form.tipo_documento === 'DNI' && !/^\d{8}$/.test(this.form.numero_documento.trim())) {
        return 'El DNI debe tener 8 dígitos';
      }
      if (this.esCasado && (!this.conyuge.nombres.trim() || !this.conyuge.apellidos.trim() || !this.conyuge.numero_documento.trim())) {
        return 'Si el estado civil es casado, completa los datos del cónyuge';
      }
    }
    if (!this.form.telefono.trim()) return 'El teléfono es obligatorio';
    if (!this.form.direccion.trim()) return 'La dirección es obligatoria';
    return null;
  }

  guardar(): void {
    const errorValidacion = this.validar();
    if (errorValidacion) {
      this.error.set(errorValidacion);
      return;
    }
    this.error.set(null);
    this.guardando.set(true);

    const conyugePayload = this.esCasado
      ? { ...this.conyuge, telefono: this.conyuge.telefono || undefined }
      : undefined;

    if (this.esEdicion) {
      const payload: ClienteUpdate = {
        correo: this.form.correo || undefined,
        telefono: this.form.telefono,
        direccion: this.form.direccion,
        dni_url: this.form.dni_url || undefined,
        fecha_nacimiento: this.form.fecha_nacimiento || undefined,
        estado_civil: (this.form.estado_civil || undefined) as EstadoCivil | undefined,
        segundo_contacto_nombre: this.form.segundo_contacto_nombre || undefined,
        segundo_contacto_telefono: this.form.segundo_contacto_telefono || undefined,
        ruc: this.form.ruc || undefined,
        razon_social: this.form.razon_social || undefined,
        representante_legal: this.form.representante_legal || undefined,
        conyuge: conyugePayload,
      };
      this.clienteService.actualizar(this.idCliente!, payload).subscribe({
        next: () => {
          this.guardando.set(false);
          this.toastService.exito('Cliente actualizado correctamente');
          this.router.navigate(['/dashboard/clientes', this.idCliente]);
        },
        error: (err) => {
          this.guardando.set(false);
          const mensaje = err?.error?.detail ?? 'No se pudo actualizar el cliente';
          this.error.set(mensaje);
          this.toastService.error(mensaje);
        },
      });
    } else {
      const payload: ClienteCreate = {
        tipo_persona: this.form.tipo_persona,
        tipo_documento: this.form.tipo_documento,
        numero_documento: this.form.numero_documento.trim(),
        nombres: this.form.nombres.trim(),
        apellidos: this.form.apellidos.trim(),
        correo: this.form.correo || undefined,
        telefono: this.form.telefono,
        direccion: this.form.direccion,
        dni_url: this.form.dni_url || undefined,
        fecha_nacimiento: this.form.fecha_nacimiento || undefined,
        estado_civil: (this.form.estado_civil || undefined) as EstadoCivil | undefined,
        segundo_contacto_nombre: this.form.segundo_contacto_nombre || undefined,
        segundo_contacto_telefono: this.form.segundo_contacto_telefono || undefined,
        ruc: this.form.ruc || undefined,
        razon_social: this.form.razon_social || undefined,
        representante_legal: this.form.representante_legal || undefined,
        conyuge: conyugePayload,
      };
      this.clienteService.crear(payload).subscribe({
        next: (cliente) => {
          this.guardando.set(false);
          this.toastService.exito('Cliente creado correctamente');
          if (this.returnTo) {
            const queryParams: Record<string, string> = { id_cliente: String(cliente.id) };
            if (this.idProyectoReturn) queryParams['id_proyecto'] = this.idProyectoReturn;
            this.router.navigate([this.returnTo], { queryParams });
          } else {
            this.router.navigate(['/dashboard/clientes', cliente.id]);
          }
        },
        error: (err) => {
          this.guardando.set(false);
          const mensaje = err?.error?.detail ?? 'No se pudo crear el cliente';
          this.error.set(mensaje);
          this.toastService.error(mensaje);
        },
      });
    }
  }

  cancelar(): void {
    if (this.esEdicion) {
      this.router.navigate(['/dashboard/clientes', this.idCliente]);
    } else {
      this.router.navigate(['/dashboard/clientes']);
    }
  }
}