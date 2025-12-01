import React, { useMemo, useState } from 'react';
import { useTheme } from '../../styles/ThemeContext';
import { hexToRgba, softGradient, focusRing } from './styles';
import type { ButtonSize, ButtonVariant } from './types';

type ButtonProps = {
  variant?: ButtonVariant;
  size?: ButtonSize;
  isLoading?: boolean;
  fullWidth?: boolean;
} & React.ButtonHTMLAttributes<HTMLButtonElement>;

type VariantStyle = {
  background: string;
  border: string;
  color: string;
  hoverBackground: string;
  hoverBorder: string;
  baseShadow?: string;
  hoverShadow?: string;
};

const getVariantStyle = (theme: ReturnType<typeof useTheme>, variant: ButtonVariant): VariantStyle => {
  switch (variant) {
    case 'secondary':
      return {
        background: theme.colors.surface,
        border: `1px solid ${theme.colors.border}`,
        color: theme.colors.text,
        hoverBackground: theme.colors.surfaceAlt,
        hoverBorder: `1px solid ${theme.colors.borderStrong}`,
        baseShadow: 'none',
        hoverShadow: theme.shadow.card,
      };
    case 'ghost':
      return {
        background: 'transparent',
        border: `1px solid ${theme.colors.border}`,
        color: theme.colors.textMuted,
        hoverBackground: hexToRgba(theme.colors.primary, 0.08),
        hoverBorder: `1px solid ${theme.colors.borderStrong}`,
        baseShadow: 'none',
        hoverShadow: theme.shadow.card,
      };
    case 'danger':
      return {
        background: softGradient(theme.colors.danger, theme.colors.danger),
        border: `1px solid ${hexToRgba(theme.colors.danger, 0.65)}`,
        color: '#fee2e2',
        hoverBackground: softGradient(theme.colors.danger, theme.colors.danger),
        hoverBorder: `1px solid ${hexToRgba(theme.colors.danger, 0.85)}`,
        baseShadow: '0 12px 22px rgba(248, 113, 113, 0.25)',
        hoverShadow: '0 16px 28px rgba(248, 113, 113, 0.35)',
      };
    case 'primary':
    default:
      return {
        background: softGradient(theme.colors.primary, theme.colors.info),
        border: `1px solid ${hexToRgba(theme.colors.info, 0.75)}`,
        color: '#e0f2fe',
        hoverBackground: softGradient(theme.colors.primary, theme.colors.info),
        hoverBorder: `1px solid ${hexToRgba(theme.colors.info, 0.95)}`,
        baseShadow: '0 12px 22px rgba(14, 165, 233, 0.25)',
        hoverShadow: '0 16px 28px rgba(14, 165, 233, 0.35)',
      };
  }
};

const getSizeStyle = (theme: ReturnType<typeof useTheme>, size: ButtonSize) => {
  switch (size) {
    case 'sm':
      return {
        padding: `${theme.spacing.xs} ${theme.spacing.md}`,
        fontSize: theme.typography.fontSizeSm,
      };
    case 'lg':
      return {
        padding: `${theme.spacing.md} ${theme.spacing.xl}`,
        fontSize: theme.typography.fontSizeLg,
      };
    case 'md':
    default:
      return {
        padding: `${theme.spacing.sm} ${theme.spacing.lg}`,
        fontSize: theme.typography.fontSizeBase,
      };
  }
};

function Button({
  variant = 'primary',
  size = 'md',
  isLoading = false,
  fullWidth = false,
  disabled,
  children,
  style,
  ...props
}: ButtonProps): JSX.Element {
  const theme = useTheme();
  const [isHovered, setIsHovered] = useState(false);
  const [isFocused, setIsFocused] = useState(false);

  const variantStyles = useMemo(() => getVariantStyle(theme, variant), [theme, variant]);
  const sizeStyles = useMemo(() => getSizeStyle(theme, size), [theme, size]);

  const baseShadow = isHovered ? variantStyles.hoverShadow ?? variantStyles.baseShadow : variantStyles.baseShadow;
  const boxShadow = isFocused
    ? [baseShadow, focusRing(theme)].filter(Boolean).join(', ')
    : baseShadow;

  const computedStyle: React.CSSProperties = {
    background: isHovered ? variantStyles.hoverBackground : variantStyles.background,
    border: isHovered ? variantStyles.hoverBorder : variantStyles.border,
    color: variantStyles.color,
    borderRadius: theme.radii.md,
    fontWeight: theme.typography.fontWeightBold,
    fontFamily: theme.typography.fontFamily,
    cursor: disabled || isLoading ? 'not-allowed' : 'pointer',
    opacity: disabled ? 0.6 : 1,
    transition: 'background 0.18s ease, border-color 0.18s ease, transform 0.18s ease, box-shadow 0.18s ease',
    boxShadow,
    transform: isHovered && !disabled && !isLoading ? 'translateY(-1px)' : undefined,
    display: 'inline-flex',
    alignItems: 'center',
    justifyContent: 'center',
    gap: '0.5rem',
    width: fullWidth ? '100%' : undefined,
    ...sizeStyles,
    ...(isFocused ? { outline: 'none' } : {}),
    ...style,
  };

  return (
    <button
      type="button"
      {...props}
      aria-busy={isLoading}
      disabled={disabled || isLoading}
      onMouseEnter={(event) => {
        setIsHovered(true);
        props.onMouseEnter?.(event);
      }}
      onMouseLeave={(event) => {
        setIsHovered(false);
        props.onMouseLeave?.(event);
      }}
      onFocus={(event) => {
        setIsFocused(true);
        props.onFocus?.(event);
      }}
      onBlur={(event) => {
        setIsFocused(false);
        props.onBlur?.(event);
      }}
      style={computedStyle}
    >
      {isLoading ? (
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: '0.5rem' }}>
          <svg
            width="18"
            height="18"
            viewBox="0 0 24 24"
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
            aria-hidden
          >
            <circle
              cx="12"
              cy="12"
              r="9"
              stroke={hexToRgba(theme.colors.text, 0.25)}
              strokeWidth="3"
              strokeLinecap="round"
            />
            <path
              d="M21 12a9 9 0 0 0-9-9"
              stroke={variant === 'ghost' ? theme.colors.primary : theme.colors.text}
              strokeWidth="3"
              strokeLinecap="round"
            >
              <animateTransform
                attributeName="transform"
                type="rotate"
                from="0 12 12"
                to="360 12 12"
                dur="0.9s"
                repeatCount="indefinite"
              />
            </path>
          </svg>
          <span style={{ visibility: 'hidden' }}>{children}</span>
        </span>
      ) : (
        children
      )}
    </button>
  );
}

export default Button;
