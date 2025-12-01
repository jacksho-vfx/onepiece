import React, { useState } from 'react';
import { useTheme } from '../../styles/ThemeContext';
import { focusRing } from './styles';

type Tab = { id: string; label: string };

type TabsProps = {
  tabs: Tab[];
  activeTabId: string;
  onTabChange: (id: string) => void;
};

function Tabs({ tabs, activeTabId, onTabChange }: TabsProps): JSX.Element {
  const theme = useTheme();
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [focusedId, setFocusedId] = useState<string | null>(null);

  return (
    <div
      role="tablist"
      aria-orientation="horizontal"
      style={{
        display: 'flex',
        gap: theme.spacing.sm,
        flexWrap: 'wrap',
        alignItems: 'center',
      }}
    >
      {tabs.map((tab) => {
        const isActive = tab.id === activeTabId;
        const isHovered = tab.id === hoveredId;
        const isFocused = tab.id === focusedId;

        return (
          <button
            key={tab.id}
            role="tab"
            type="button"
            aria-selected={isActive}
            onClick={() => onTabChange(tab.id)}
            onMouseEnter={() => setHoveredId(tab.id)}
            onMouseLeave={() => setHoveredId(null)}
            onFocus={() => setFocusedId(tab.id)}
            onBlur={() => setFocusedId(null)}
            style={{
              position: 'relative',
              border: `1px solid ${isActive ? theme.colors.borderStrong : theme.colors.border}`,
              background: isActive ? theme.colors.primarySoft : 'rgba(255,255,255,0.02)',
              color: isActive ? theme.colors.text : theme.colors.textMuted,
              padding: `${theme.spacing.sm} ${theme.spacing.lg}`,
              borderRadius: theme.radii.md,
              cursor: 'pointer',
              fontWeight: theme.typography.fontWeightMedium,
              letterSpacing: '0.02em',
              transition: 'all 0.18s ease-in-out',
              boxShadow: isActive
                ? `${theme.shadow.card}, ${focusRing(theme)}`
                : isFocused
                  ? focusRing(theme)
                  : undefined,
              outline: 'none',
              transform: isHovered && !isActive ? 'translateY(-1px)' : undefined,
            }}
          >
            <span>{tab.label}</span>
            {isActive ? (
              <span
                aria-hidden
                style={{
                  position: 'absolute',
                  left: '10%',
                  right: '10%',
                  bottom: -3,
                  height: '3px',
                  borderRadius: '999px',
                  background: theme.colors.info,
                  boxShadow: focusRing(theme),
                }}
              />
            ) : null}
          </button>
        );
      })}
    </div>
  );
}

export default Tabs;
