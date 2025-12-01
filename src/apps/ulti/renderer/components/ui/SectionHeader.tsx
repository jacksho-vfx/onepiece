import React from 'react';
import { useTheme } from '../../styles/ThemeContext';

export type SectionHeaderProps = {
  title: string;
  subtitle?: string;
  action?: React.ReactNode;
};

function SectionHeader({ title, subtitle, action }: SectionHeaderProps): JSX.Element {
  const theme = useTheme();

  return (
    <div
      style={{
        display: 'flex',
        alignItems: subtitle ? 'flex-start' : 'center',
        justifyContent: 'space-between',
        gap: theme.spacing.md,
        paddingBottom: theme.spacing.sm,
        borderBottom: `1px solid ${theme.colors.border}`,
      }}
    >
      <div style={{ display: 'grid', gap: '0.2rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: theme.spacing.sm }}>
          <span
            aria-hidden
            style={{
              width: '6px',
              height: '22px',
              background: `linear-gradient(180deg, ${theme.colors.primary}, ${theme.colors.info})`,
              borderRadius: theme.radii.xs,
              boxShadow: theme.shadow.card,
              opacity: 0.9,
            }}
          />
          <h2 style={{ margin: 0, letterSpacing: '0.01em' }}>{title}</h2>
        </div>
        {subtitle ? <p style={{ margin: 0, color: theme.colors.textMuted }}>{subtitle}</p> : null}
      </div>
      {action ? (
        <div style={{ display: 'flex', alignItems: 'center', gap: theme.spacing.sm, marginLeft: 'auto' }}>{action}</div>
      ) : null}
    </div>
  );
}

export default SectionHeader;
