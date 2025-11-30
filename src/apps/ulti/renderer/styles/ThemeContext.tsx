import React, { createContext, useContext, useEffect, useMemo } from 'react';
import { designTokens } from './designTokens';

export type Theme = typeof designTokens;

export const ThemeContext = createContext<Theme>(designTokens);

const toKebabCase = (value: string) => value.replace(/([a-z0-9])([A-Z])/g, '$1-$2').toLowerCase();

const setCssVariables = (theme: Theme) => {
  const root = document.documentElement;
  const appliedVariables: string[] = [];

  const applyGroup = (tokens: Record<string, string | number>, prefix: string) => {
    Object.entries(tokens).forEach(([key, tokenValue]) => {
      const varName = `--op-${prefix}-${toKebabCase(key)}`;
      root.style.setProperty(varName, String(tokenValue));
      appliedVariables.push(varName);
    });
  };

  applyGroup(theme.colors, 'color');
  applyGroup(theme.radii, 'radius');
  applyGroup(theme.spacing, 'spacing');
  applyGroup(theme.shadow, 'shadow');
  applyGroup(theme.typography, 'typography');

  return () => {
    appliedVariables.forEach((variable) => {
      root.style.removeProperty(variable);
    });
  };
};

export const ThemeProvider = ({ children }: { children: React.ReactNode }): JSX.Element => {
  const theme = useMemo(() => designTokens, []);

  useEffect(() => {
    const cleanup = setCssVariables(theme);
    return cleanup;
  }, [theme]);

  return <ThemeContext.Provider value={theme}>{children}</ThemeContext.Provider>;
};

export const useTheme = (): Theme => useContext(ThemeContext);
