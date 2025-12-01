import React from 'react';
import { useTheme } from '../../styles/ThemeContext';

type CardProps = {
  title?: string;
  children: React.ReactNode;
  style?: React.CSSProperties;
};

function Card({ title, children, style }: CardProps): JSX.Element {
  const theme = useTheme();

  return (
    <section
      style={{
        background: theme.colors.surface,
        border: `1px solid ${theme.colors.border}`,
        borderRadius: theme.radii.lg,
        boxShadow: theme.shadow.card,
        padding: theme.spacing.lg,
        display: 'grid',
        gap: theme.spacing.sm,
        color: theme.colors.text,
        ...style,
      }}
    >
      {title ? (
        <header>
          <h3 style={{ margin: 0, letterSpacing: '0.01em' }}>{title}</h3>
        </header>
      ) : null}
      <div>{children}</div>
    </section>
  );
}

export default Card;
