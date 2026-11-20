function hexToRgb(hex: string): { r: number; g: number; b: number } {
  let limpio = hex.replace('#', '');
  if (limpio.length === 3) {
    limpio = limpio.split('').map((c) => c + c).join('');
  }
  const num = parseInt(limpio, 16);
  return { r: (num >> 16) & 255, g: (num >> 8) & 255, b: num & 255 };
}

function rgbToHex(r: number, g: number, b: number): string {
  const clamp = (n: number) => Math.max(0, Math.min(255, Math.round(n)));
  return '#' + [clamp(r), clamp(g), clamp(b)].map((v) => v.toString(16).padStart(2, '0')).join('');
}

function mezclar(hex: string, hacia: string, peso: number): string {
  const a = hexToRgb(hex);
  const b = hexToRgb(hacia);
  return rgbToHex(a.r + (b.r - a.r) * peso, a.g + (b.g - a.g) * peso, a.b + (b.b - a.b) * peso);
}

export function aclarar(hex: string, cantidad: number): string {
  return mezclar(hex, '#ffffff', cantidad);
}

export function oscurecer(hex: string, cantidad: number): string {
  return mezclar(hex, '#000000', cantidad);
}

/** Luminancia relativa (WCAG) — decide si un color es "claro" u "oscuro" */
export function luminancia(hex: string): number {
  const { r, g, b } = hexToRgb(hex);
  const canal = (v: number) => {
    const c = v / 255;
    return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
  };
  return 0.2126 * canal(r) + 0.7152 * canal(g) + 0.0722 * canal(b);
}

/** Blanco o casi-negro, el que dé mejor contraste sobre `hex` */
export function textoLegibleSobre(hex: string): string {
  return luminancia(hex) > 0.45 ? '#14201c' : '#ffffff';
}

/** Si `hex` es muy claro para usarse como texto sobre fondo blanco, lo oscurece */
export function versionLegibleSobreBlanco(hex: string): string {
  return luminancia(hex) > 0.55 ? oscurecer(hex, 0.35) : hex;
}

export interface PaletaTenant {
  '--color-primario': string;
  '--color-primario-claro': string;
  '--color-primario-oscuro': string;
  '--color-primario-suave': string;
  '--color-primario-suave-50': string;
  '--color-secundario': string;
  '--color-secundario-claro': string;
  '--color-secundario-oscuro': string;
  '--color-secundario-superclaro': string;
  '--color-borde': string;
  '--texto-sobre-primario': string;
  '--texto-sobre-secundario': string;
  '--primario-legible': string;
  '--secundario-legible': string;
}

export function construirPaleta(colorPrimario: string, colorSecundario: string): PaletaTenant {
  return {
    '--color-primario': colorPrimario,
    '--color-primario-claro': aclarar(colorPrimario, 0.28),
    '--color-primario-oscuro': oscurecer(colorPrimario, 0.22),
    '--color-primario-suave': aclarar(colorPrimario, 0.85),
    '--color-primario-suave-50': aclarar(colorPrimario, 0.94),
    '--color-secundario': colorSecundario,
    '--color-secundario-claro': aclarar(colorSecundario, 0.28),
    '--color-secundario-oscuro': oscurecer(colorSecundario, 0.22),
    '--color-secundario-superclaro': aclarar(colorSecundario, 0.97),
    '--color-borde': aclarar(colorSecundario, 0.88),
    '--texto-sobre-primario': textoLegibleSobre(colorPrimario),
    '--texto-sobre-secundario': textoLegibleSobre(colorSecundario),
    '--primario-legible': versionLegibleSobreBlanco(colorPrimario),
    '--secundario-legible': versionLegibleSobreBlanco(colorSecundario),
  };
}

/** Aplica la paleta completa como custom properties en :root */
export function aplicarPaletaEnDocumento(colorPrimario: string, colorSecundario: string): void {
  const paleta = construirPaleta(colorPrimario, colorSecundario);
  const root = document.documentElement.style;
  Object.entries(paleta).forEach(([variable, valor]) => root.setProperty(variable, valor));
}