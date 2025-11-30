import React from 'react';
import { designTokens } from '../../styles/designTokens';

export type NavItem = {
  id: string;
  label: string;
  onSelect?: (id: string) => void;
};

export type AppShellProps = {
  children: React.ReactNode;
  navItems?: NavItem[];
  activeNavId?: string;
  showNav?: boolean;
  headerTitle?: string;
  headerSubtitle?: string;
};

const backgroundLayer = `radial-gradient(circle at 20% 20%, rgba(56, 189, 248, 0.12), transparent 38%),
radial-gradient(circle at 80% 0%, rgba(14, 165, 233, 0.1), transparent 45%),
${designTokens.colors.background}`;

const headerGradient = `linear-gradient(135deg, rgba(56, 189, 248, 0.16), rgba(14, 165, 233, 0.08)), linear-gradient(135deg, #1f2937, #0b1120)`;

function AppShell({
  children,
  navItems = [],
  activeNavId,
  showNav = true,
  headerTitle = 'OnePiece Studio Desktop',
  headerSubtitle,
}: AppShellProps): JSX.Element {
  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        flexDirection: 'column',
        background: backgroundLayer,
        color: designTokens.colors.text,
        fontFamily: designTokens.typography.fontFamily,
      }}
    >
      <header
        style={{
          background: headerGradient,
          padding: '1.5rem 1.75rem',
          boxShadow: designTokens.shadow.elevated,
          borderBottom: `1px solid ${designTokens.colors.border}`,
          display: 'flex',
          flexDirection: 'column',
          gap: '0.75rem',
          position: 'sticky',
          top: 0,
          zIndex: 10,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '1rem' }}>
          <div>
            <p
              style={{
                margin: 0,
                color: designTokens.colors.textMuted,
                letterSpacing: '0.04em',
                textTransform: 'uppercase',
                fontSize: designTokens.typography.fontSizeSm,
                fontWeight: designTokens.typography.fontWeightMedium,
              }}
            >
              OnePiece
            </p>
            <h1 style={{ margin: '0.15rem 0 0', fontSize: '1.6rem', letterSpacing: '0.01em' }}>{headerTitle}</h1>
            {headerSubtitle ? (
              <p style={{ margin: '0.35rem 0 0', color: designTokens.colors.textMuted }}>{headerSubtitle}</p>
            ) : null}
          </div>
          <div
            aria-hidden
            style={{
              height: '48px',
              minWidth: '48px',
              borderRadius: designTokens.radii.lg,
              background: `linear-gradient(135deg, rgba(56, 189, 248, 0.35), rgba(14, 165, 233, 0.2))`,
              boxShadow: designTokens.shadow.card,
              display: 'inline-flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: designTokens.colors.text,
              fontWeight: designTokens.typography.fontWeightBold,
            }}
          >
            OP
          </div>
        </div>

        {showNav && navItems.length ? (
          <nav
            style={{
              display: 'flex',
              gap: '0.5rem',
              flexWrap: 'wrap',
              alignItems: 'center',
            }}
          >
            {navItems.map((item) => {
              const isActive = activeNavId === item.id;
              return (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => item.onSelect?.(item.id)}
                  style={{
                    border: `1px solid ${isActive ? designTokens.colors.borderStrong : designTokens.colors.border}`,
                    color: isActive ? designTokens.colors.text : designTokens.colors.textMuted,
                    background: isActive ? designTokens.colors.primarySoft : 'rgba(255,255,255,0.02)',
                    padding: `${designTokens.spacing.sm} ${designTokens.spacing.lg}`,
                    borderRadius: '999px',
                    cursor: 'pointer',
                    fontWeight: designTokens.typography.fontWeightMedium,
                    letterSpacing: '0.02em',
                    transition: 'all 0.18s ease-in-out',
                    boxShadow: isActive ? designTokens.shadow.card : undefined,
                  }}
                >
                  {item.label}
                </button>
              );
            })}
          </nav>
        ) : null}
      </header>

      <main
        style={{
          flex: 1,
          display: 'flex',
          overflowY: 'auto',
        }}
      >
        <div
          style={{
            width: 'min(1200px, 100%)',
            margin: '0 auto',
            padding: '2rem 1.5rem 2.5rem',
            display: 'flex',
            flexDirection: 'column',
            gap: '1.25rem',
          }}
        >
          {children}
        </div>
      </main>
    </div>
  );
}

export default AppShell;
