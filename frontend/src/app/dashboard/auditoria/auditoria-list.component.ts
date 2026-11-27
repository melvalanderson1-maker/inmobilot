import { CommonModule } from '@angular/common';
import { Component, OnInit, computed, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { ApiService } from '../../core/services/api.service';

interface OpcionAud { valor: string; etiqueta: string }
interface RegistroAud {
  id: number;
  fecha: string | null;
  usuario: string | null;
  entidad: string;
  id_entidad: number;
  referencia: string;
  accion: string;
  accion_texto: string;
  cambios: Record<string, any> | null;
}
interface RespuestaAud { total: number; pagina: number; por_pagina: number; items: RegistroAud[] }
interface OpcionesAud {
  usuarios: { id: number; nombre: string }[];
  entidades: OpcionAud[];
  acciones: OpcionAud[];
}

const NOMBRES_CAMPO: Record<string, string> = {
  comprobante_url: 'Voucher / archivo',
  monto: 'Monto',
  fecha_pago: 'Fecha de pago',
  metodo_pago: 'Método de pago',
  numero_operacion: 'N° de operación',
  observacion: 'Observación',
  motivo: 'Motivo',
  motivo_rechazo_previo: 'Motivo de rechazo previo',
  id_contrato: 'Contrato (id)',
  id_separacion: 'Separación (id)',
  id_lote: 'Lote (id)',
  importe: 'Importe',
  numero: 'Número',
  tipo: 'Tipo',
  archivo_url: 'Archivo',
  voucher_url: 'Voucher',
  voucher_numero: 'N° de operación',
  nota_credito_numero: 'N° nota de crédito',
  nota_credito_url: 'Archivo nota de crédito',
  fecha_inicio: 'Fecha de inicio',
  fecha_vencimiento: 'Fecha de vencimiento',
};

@Component({
  selector: 'app-auditoria-list',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './auditoria-list.component.html',
  styleUrl: './auditoria-list.component.css',
})
export class AuditoriaListComponent implements OnInit {
  opciones = signal<OpcionesAud>({ usuarios: [], entidades: [], acciones: [] });
  registros = signal<RegistroAud[]>([]);
  total = signal(0);
  pagina = signal(1);
  cargando = signal(false);
  abierto = signal<number | null>(null);

  readonly porPagina = 50;
  totalPaginas = computed(() => Math.max(1, Math.ceil(this.total() / this.porPagina)));

  filtros = { entidad: '', accion: '', id_usuario: '', id_entidad: '', desde: '', hasta: '' };

  constructor(private api: ApiService) {}

  ngOnInit(): void {
    this.api.get<OpcionesAud>('/auditoria/opciones').subscribe((o) => this.opciones.set(o));
    this.buscar();
  }

  buscar(pagina = 1): void {
    this.pagina.set(pagina);
    this.cargando.set(true);
    const params: Record<string, string | number> = { pagina, por_pagina: this.porPagina };
    for (const [k, v] of Object.entries(this.filtros)) {
      if (v !== '' && v !== null) params[k] = v as string;
    }
    this.api.get<RespuestaAud>('/auditoria/buscar', params).subscribe({
      next: (r) => {
        this.registros.set(r.items);
        this.total.set(r.total);
        this.cargando.set(false);
      },
      error: () => this.cargando.set(false),
    });
  }

  limpiar(): void {
    this.filtros = { entidad: '', accion: '', id_usuario: '', id_entidad: '', desde: '', hasta: '' };
    this.buscar();
  }

  alternar(id: number): void {
    this.abierto.set(this.abierto() === id ? null : id);
  }

  fmtFecha(f: string | null): string {
    if (!f) return '—';
    const d = new Date(f.endsWith('Z') || f.includes('+') ? f : f + 'Z');
    return d.toLocaleString('es-PE', { timeZone: 'America/Lima', hour12: false });
  }

  private fmt(v: any): string {
    if (v === null || v === undefined || v === '') return '—';
    return typeof v === 'object' ? JSON.stringify(v) : String(v);
  }

  esUrl(t: string): boolean {
    return t.startsWith('http://') || t.startsWith('https://');
  }

  detalle(c: Record<string, any> | null) {
    if (!c) return [];
    return Object.entries(c).map(([campo, v]) => {
      const esCambio = v && typeof v === 'object' && 'antes' in v && 'despues' in v;
      return {
        campo: NOMBRES_CAMPO[campo] ?? campo,
        cambio: !!esCambio,
        antes: esCambio ? this.fmt(v.antes) : '',
        despues: esCambio ? this.fmt(v.despues) : this.fmt(v),
      };
    });
  }
}