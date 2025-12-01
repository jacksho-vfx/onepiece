import React, { useEffect } from 'react';
import ReactDOM from 'react-dom';
import { useTheme } from '../../styles/ThemeContext';
import Button from './Button';
import type { ButtonVariant } from './types';

export type ModalAction = {
  label: string;
  onClick: () => void;
  variant?: ButtonVariant;
  isLoading?: boolean;
  disabled?: boolean;
};

export type ModalProps = {
  title: string;
  description?: string;
  children: React.ReactNode;
  isOpen: boolean;
  onClose: () => void;
  primaryAction: ModalAction;
  secondaryAction?: ModalAction;
};

const modalRoot = typeof document !== 'undefined' ? document.body : null;

function Modal({
  title,
  description,
  children,
  isOpen,
  onClose,
  primaryAction,
  secondaryAction,
}: ModalProps): JSX.Element | null {
  const theme = useTheme();

  useEffect(() => {
    if (!isOpen) return undefined;

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        onClose();
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [isOpen, onClose]);

  if (!isOpen || !modalRoot) {
    return null;
  }

  const handleBackdropClick = (event: React.MouseEvent<HTMLDivElement>) => {
    if (event.target === event.currentTarget) {
      onClose();
    }
  };

  return ReactDOM.createPortal(
    <div
      role="presentation"
      onClick={handleBackdropClick}
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(5, 10, 20, 0.6)',
        backdropFilter: 'blur(4px)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: theme.spacing.lg,
        zIndex: 1000,
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="op-modal-title"
        aria-describedby={description ? 'op-modal-description' : undefined}
        style={{
          background: theme.colors.surface,
          color: theme.colors.text,
          border: `1px solid ${theme.colors.border}`,
          borderRadius: theme.radii.lg,
          boxShadow: theme.shadow.elevated,
          minWidth: 'min(720px, 100%)',
          maxWidth: 'min(860px, 95vw)',
          padding: theme.spacing.lg,
          display: 'flex',
          flexDirection: 'column',
          gap: theme.spacing.md,
        }}
      >
        <header style={{ display: 'flex', justifyContent: 'space-between', gap: theme.spacing.md }}>
          <div style={{ display: 'grid', gap: '0.25rem' }}>
            <p
              style={{
                margin: 0,
                letterSpacing: '0.04em',
                textTransform: 'uppercase',
                color: theme.colors.textMuted,
                fontSize: theme.typography.fontSizeSm,
              }}
            >
              OnePiece Studio
            </p>
            <h3 id="op-modal-title" style={{ margin: 0 }}>
              {title}
            </h3>
            {description ? (
              <p id="op-modal-description" style={{ margin: 0, color: theme.colors.textMuted }}>
                {description}
              </p>
            ) : null}
          </div>
          <Button variant="ghost" aria-label="Close dialog" onClick={onClose}>
            Close
          </Button>
        </header>

        <div style={{
          padding: `${theme.spacing.sm} ${theme.spacing.sm} ${theme.spacing.md}`,
          background: theme.colors.surfaceAlt,
          borderRadius: theme.radii.md,
          border: `1px solid ${theme.colors.border}`,
          boxShadow: theme.shadow.card,
        }}>
          {children}
        </div>

        <footer
          style={{
            display: 'flex',
            justifyContent: 'flex-end',
            gap: theme.spacing.sm,
            paddingTop: theme.spacing.sm,
            borderTop: `1px solid ${theme.colors.border}`,
          }}
        >
          {secondaryAction ? (
            <Button
              variant={secondaryAction.variant ?? 'secondary'}
              onClick={secondaryAction.onClick}
              disabled={secondaryAction.disabled}
              isLoading={secondaryAction.isLoading}
            >
              {secondaryAction.label}
            </Button>
          ) : null}
          <Button
            variant={primaryAction.variant ?? 'primary'}
            onClick={primaryAction.onClick}
            disabled={primaryAction.disabled}
            isLoading={primaryAction.isLoading}
          >
            {primaryAction.label}
          </Button>
        </footer>
      </div>
    </div>,
    modalRoot,
  );
}

export default Modal;
