/**
 * Dado un color hex (#rrggbb), devuelve '#ffffff' o '#0a0a0a' —
 * el que dé mejor contraste de lectura encima de ese color.
 * Basado en luminancia relativa (fórmula WCAG).
 */
export function calcularColorTexto(colorHex: string): string {
  const hex = colorHex.replace('#', '');
  if (hex.length !== 6) return '#ffffff';

  const r = parseInt(hex.substring(0, 2), 16) / 255;
  const g = parseInt(hex.substring(2, 4), 16) / 255;
  const b = parseInt(hex.substring(4, 6), 16) / 255;

  const canal = (c: number) => (c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4));
  const luminancia = 0.2126 * canal(r) + 0.7152 * canal(g) + 0.0722 * canal(b);

  return luminancia > 0.5 ? '#0a0a0a' : '#ffffff';
}

/**
 * Cuando el color elegido (primario/secundario) se usa como color de
 * ICONO o TEXTO sobre el fondo blanco de la página (no como fondo), un
 * color muy claro (blanco, amarillo pálido) se vuelve invisible. Esta
 * función oscurece el color manteniendo su tono si es demasiado claro
 * para leerse sobre blanco — así "Limpiar filtros" o los íconos nunca
 * desaparecen, sin importar qué color elija cada inmobiliaria.
 */
export function asegurarLegibleSobreBlanco(colorHex: string): string {
  const hex = colorHex.replace('#', '');
  if (hex.length !== 6) return colorHex;

  let r = parseInt(hex.substring(0, 2), 16) / 255;
  let g = parseInt(hex.substring(2, 4), 16) / 255;
  let b = parseInt(hex.substring(4, 6), 16) / 255;

  const max = Math.max(r, g, b), min = Math.min(r, g, b);
  let h = 0, s = 0;
  const l = (max + min) / 2;

  if (max !== min) {
    const d = max - min;
    s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
    if (max === r) h = ((g - b) / d + (g < b ? 6 : 0)) / 6;
    else if (max === g) h = ((b - r) / d + 2) / 6;
    else h = ((r - g) / d + 4) / 6;
  }

  // Si es demasiado claro para leerse sobre blanco, lo bajamos a 45% de luz
  const lFinal = l > 0.72 ? 0.45 : l;

  const hue2rgb = (p: number, q: number, t: number) => {
    if (t < 0) t += 1;
    if (t > 1) t -= 1;
    if (t < 1 / 6) return p + (q - p) * 6 * t;
    if (t < 1 / 2) return q;
    if (t < 2 / 3) return p + (q - p) * (2 / 3 - t) * 6;
    return p;
  };

  if (s === 0) { r = g = b = lFinal; }
  else {
    const q = lFinal < 0.5 ? lFinal * (1 + s) : lFinal + s - lFinal * s;
    const p = 2 * lFinal - q;
    r = hue2rgb(p, q, h + 1 / 3);
    g = hue2rgb(p, q, h);
    b = hue2rgb(p, q, h - 1 / 3);
  }

  const toHex = (c: number) => Math.round(c * 255).toString(16).padStart(2, '0');
  return `#${toHex(r)}${toHex(g)}${toHex(b)}`;
}