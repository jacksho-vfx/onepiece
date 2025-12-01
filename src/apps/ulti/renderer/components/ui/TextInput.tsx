import React, { useId, useMemo, useState } from 'react';
import { useTheme } from '../../styles/ThemeContext';
import { focusRing, hexToRgba } from './styles';

type TextInputProps = {
  label?: string;
  helpText?: string;
  errorText?: string;
} & React.InputHTMLAttributes<HTMLInputElement>;

function TextInput({ label, helpText, errorText, id, disabled, style, ...props }: TextInputProps): JSX.Element {
  const theme = useTheme();
  const [isFocused, setIsFocused] = useState(false);
  const inputId = useMemo(() => id ?? useId(), [id]);
  const describedByIds = [helpText ? `${inputId}-help` : undefined, errorText ? `${inputId}-error` : undefined]
    .filter(Boolean)
    .join(' ');

  const borderColor = errorText ? hexToRgba(theme.colors.danger, 0.8) : theme.colors.border;
  const focusBorderColor = errorText ? hexToRgba(theme.colors.danger, 0.95) : theme.colors.borderStrong;
  const focusShadow = errorText
    ? `0 0 0 3px ${hexToRgba(theme.colors.danger, 0.25)}`
    : focusRing(theme);

  return (
    <label style={{ display: 'grid', gap: '0.35rem', width: '100%' }} htmlFor={inputId}>
      {label ? (
        <span
          style={{
            fontWeight: theme.typography.fontWeightMedium,
            color: theme.colors.text,
            fontSize: theme.typography.fontSizeSm,
          }}
        >
          {label}
        </span>
      ) : null}

      <input
        id={inputId}
        disabled={disabled}
        aria-disabled={disabled}
        aria-describedby={describedByIds || undefined}
        style={{
          background: theme.colors.surfaceAlt,
          color: theme.colors.text,
          border: `1px solid ${isFocused ? focusBorderColor : borderColor}`,
          borderRadius: theme.radii.md,
          padding: `${theme.spacing.sm} ${theme.spacing.md}`,
          fontSize: theme.typography.fontSizeBase,
          fontFamily: theme.typography.fontFamily,
          transition: 'border-color 0.15s ease, box-shadow 0.15s ease',
          boxShadow: isFocused ? focusShadow : 'none',
          outline: 'none',
          opacity: disabled ? 0.6 : 1,
          ...style,
        }}
        onFocus={(event) => {
          setIsFocused(true);
          props.onFocus?.(event);
        }}
        onBlur={(event) => {
          setIsFocused(false);
          props.onBlur?.(event);
        }}
        {...props}
      />

      {helpText ? (
        <span
          id={`${inputId}-help`}
          style={{ color: theme.colors.textMuted, fontSize: theme.typography.fontSizeSm }}
        >
          {helpText}
        </span>
      ) : null}

      {errorText ? (
        <span
          id={`${inputId}-error`}
          style={{ color: theme.colors.danger, fontSize: theme.typography.fontSizeSm, fontWeight: 600 }}
        >
          {errorText}
        </span>
      ) : null}
    </label>
  );
}

export default TextInput;
