import React from 'react';
import { useTheme } from '../../styles/ThemeContext';
import { hexToRgba } from './styles';
import type { StatusType } from './types';

type StatusBadgeProps = {
  status: StatusType;
  children?: React.ReactNode;
};

const mapStatusToColor = (theme: ReturnType<typeof useTheme>, status: StatusType) => {
  const normalized = status.toLowerCase();

  if (normalized.includes('run') || normalized.includes('healthy') || normalized.includes('success')) {
    return theme.colors.success;
  }

  if (normalized.includes('warn')) {
    return theme.colors.warning;
  }

  if (normalized.includes('stop') || normalized.includes('fail') || normalized.includes('error')) {
    return theme.colors.danger;
  }

  return theme.colors.info;
};

function StatusBadge({ status, children }: StatusBadgeProps): JSX.Element {
  const theme = useTheme();
  const badgeColor = mapStatusToColor(theme, status);

  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: '0.4rem',
        padding: `${theme.spacing.xs} ${theme.spacing.sm}`,
        borderRadius: '999px',
        border: `1px solid ${hexToRgba(badgeColor, 0.35)}`,
        background: hexToRgba(badgeColor, 0.15),
        color: badgeColor,
        fontWeight: theme.typography.fontWeightMedium,
        letterSpacing: '0.01em',
      }}
    >
      <span
        aria-hidden
        style={{
          width: '8px',
          height: '8px',
          borderRadius: '999px',
          background: badgeColor,
          boxShadow: `0 0 0 4px ${hexToRgba(badgeColor, 0.16)}`,
        }}
      />
      <span>{children ?? status}</span>
    </span>
  );
}

export default StatusBadge;
