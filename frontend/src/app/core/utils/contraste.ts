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