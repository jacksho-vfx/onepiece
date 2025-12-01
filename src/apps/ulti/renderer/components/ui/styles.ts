import { Theme } from '../../styles/ThemeContext';

export const hexToRgba = (hex: string, alpha: number): string => {
  if (hex.startsWith('rgba')) {
    return hex;
  }

  const normalized = hex.replace('#', '');
  const chunkSize = normalized.length === 3 ? 1 : 2;
  const hexToInt = (value: string) => parseInt(value.repeat(chunkSize === 1 ? 2 : 1), 16);
  const [r, g, b] = [
    hexToInt(normalized.substring(0, chunkSize)),
    hexToInt(normalized.substring(chunkSize, chunkSize * 2)),
    hexToInt(normalized.substring(chunkSize * 2, chunkSize * 3)),
  ];

  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
};

export const softGradient = (color: string, strongColor: string): string =>
  `linear-gradient(120deg, ${hexToRgba(color, 0.35)}, ${hexToRgba(strongColor, 0.65)})`;

export const focusRing = (theme: Theme): string => theme.shadow.focusRing;
