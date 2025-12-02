import React, { createContext, useContext, useMemo, useState } from 'react';
import ReactDOM from 'react-dom';
import { useTheme } from '../../styles/ThemeContext';
import { hexToRgba } from './styles';

export type ToastKind = 'success' | 'error' | 'info';

export type ToastOptions = {
  kind?: ToastKind;
  message: string;
  durationMs?: number;
  actionLabel?: string;
  onAction?: () => void;
};

type ToastRecord = {
  id: number;
  kind: ToastKind;
  message: string;
  expiresAt: number;
  actionLabel?: string;
  onAction?: () => void;
};

type ToastContextValue = {
  showToast: (options: ToastOptions) => void;
};

const ToastContext = createContext<ToastContextValue | undefined>(undefined);

const getKindStyle = (theme: ReturnType<typeof useTheme>, kind: ToastKind) => {
  switch (kind) {
    case 'success':
      return {
        background: hexToRgba(theme.colors.success, 0.15),
        border: `1px solid ${hexToRgba(theme.colors.success, 0.65)}`,
      };
    case 'error':
      return {
        background: hexToRgba(theme.colors.danger, 0.15),
        border: `1px solid ${hexToRgba(theme.colors.danger, 0.65)}`,
      };
    case 'info':
    default:
      return {
        background: hexToRgba(theme.colors.info, 0.12),
        border: `1px solid ${hexToRgba(theme.colors.info, 0.55)}`,
      };
  }
};

const toasterRoot = typeof document !== 'undefined' ? document.body : null;

export function ToasterProvider({ children }: { children: React.ReactNode }): JSX.Element {
  const theme = useTheme();
  const [toasts, setToasts] = useState<ToastRecord[]>([]);

  const showToast = ({ kind = 'info', message, durationMs = 4200, actionLabel, onAction }: ToastOptions): void => {
    const id = Date.now() + Math.random();
    const expiresAt = Date.now() + durationMs;

    setToasts((prev) => [...prev, { id, kind, message, expiresAt, actionLabel, onAction }]);

    window.setTimeout(() => {
      setToasts((prev) => prev.filter((toast) => toast.id !== id));
    }, durationMs);
  };

  const value = useMemo(() => ({ showToast }), []);

  if (!toasterRoot) {
    return <>{children}</>;
  }

  return (
    <ToastContext.Provider value={value}>
      {children}
      {ReactDOM.createPortal(
        <div
          aria-live="polite"
          style={{
            position: 'fixed',
            bottom: theme.spacing.xl,
            right: theme.spacing.xl,
            display: 'flex',
            flexDirection: 'column',
            gap: theme.spacing.sm,
            zIndex: 1500,
          }}
        >
          {toasts.map((toast) => {
            const kindStyle = getKindStyle(theme, toast.kind);
            const isLeaving = toast.expiresAt - Date.now() < 450;

            return (
              <div
                key={toast.id}
                style={{
                  minWidth: '280px',
                  maxWidth: '340px',
                  color: theme.colors.text,
                  borderRadius: theme.radii.md,
                  boxShadow: theme.shadow.card,
                  padding: `${theme.spacing.sm} ${theme.spacing.md}`,
                  display: 'grid',
                  gap: '0.25rem',
                  transition: 'transform 0.2s ease, opacity 0.2s ease',
                  transform: isLeaving ? 'translateY(8px)' : 'translateY(0)',
                  opacity: isLeaving ? 0.5 : 1,
                  ...kindStyle,
                }}
              >
                <span
                  style={{
                    fontWeight: theme.typography.fontWeightBold,
                    letterSpacing: '0.01em',
                    textTransform: 'capitalize',
                  }}
                >
                  {toast.kind}
                </span>
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    gap: theme.spacing.md,
                  }}
                >
                  <span style={{ color: theme.colors.text, flex: 1 }}>{toast.message}</span>
                  {toast.actionLabel && toast.onAction ? (
                    <button
                      type="button"
                      onClick={toast.onAction}
                      style={{
                        border: `1px solid ${theme.colors.borderStrong}`,
                        background: hexToRgba(theme.colors.surfaceAlt, 0.8),
                        color: theme.colors.text,
                        borderRadius: theme.radii.sm,
                        padding: `${theme.spacing.xs} ${theme.spacing.sm}`,
                        cursor: 'pointer',
                        fontWeight: theme.typography.fontWeightMedium,
                      }}
                    >
                      {toast.actionLabel}
                    </button>
                  ) : null}
                </div>
              </div>
            );
          })}
        </div>,
        toasterRoot,
      )}
    </ToastContext.Provider>
  );
}

export const useToast = (): ToastContextValue => {
  const ctx = useContext(ToastContext);
  if (!ctx) {
    throw new Error('useToast must be used within a ToasterProvider');
  }
  return ctx;
};
