export type ColorTokens = {
  primary: string;
  primarySoft: string;
  background: string;
  backgroundAlt: string;
  surface: string;
  surfaceAlt: string;
  surfaceStrong: string;
  border: string;
  borderStrong: string;
  text: string;
  textMuted: string;
  success: string;
  warning: string;
  danger: string;
  info: string;
  accentGridLine: string;
};

export type RadiiTokens = {
  xs: string;
  sm: string;
  md: string;
  lg: string;
  xl: string;
};

export type SpacingTokens = {
  xs: string;
  sm: string;
  md: string;
  lg: string;
  xl: string;
};

export type ShadowTokens = {
  card: string;
  elevated: string;
  focusRing: string;
};

export type TypographyTokens = {
  fontFamily: string;
  fontSizeBase: string;
  fontSizeSm: string;
  fontSizeLg: string;
  fontWeightRegular: number;
  fontWeightMedium: number;
  fontWeightBold: number;
};

export type DesignTokens = {
  colors: ColorTokens;
  radii: RadiiTokens;
  spacing: SpacingTokens;
  shadow: ShadowTokens;
  typography: TypographyTokens;
};

export const designTokens: DesignTokens = {
  colors: {
    primary: '#38bdf8', // from src/apps/web_theme/static/theme.css: --op-accent
    primarySoft: 'rgba(56, 189, 248, 0.12)', // from src/apps/web_theme/static/theme.css: .badge background
    background: '#0b1220', // from src/apps/web_theme/static/theme.css: --op-page-bg
    backgroundAlt: '#0f172a', // from src/apps/web_theme/static/theme.css: body radial background base -> --op-surface
    surface: '#0f172a', // from src/apps/web_theme/static/theme.css: --op-surface
    surfaceAlt: '#111827', // from src/apps/web_theme/static/theme.css: --op-surface-alt
    surfaceStrong: '#0b162c', // from src/apps/web_theme/static/theme.css: --op-surface-strong
    border: 'rgba(148, 163, 184, 0.35)', // from src/apps/web_theme/static/theme.css: --op-border
    borderStrong: 'rgba(56, 189, 248, 0.55)', // from src/apps/web_theme/static/theme.css: --op-border-strong
    text: '#e2e8f0', // from src/apps/web_theme/static/theme.css: --op-text
    textMuted: '#94a3b8', // from src/apps/web_theme/static/theme.css: --op-muted
    success: '#34d399', // from src/apps/web_theme/static/theme.css: --op-success
    warning: '#fbbf24', // from src/apps/web_theme/static/theme.css: --op-warning
    danger: '#f87171', // from src/apps/web_theme/static/theme.css: --op-danger
    info: '#0ea5e9', // from src/apps/web_theme/static/theme.css: --op-accent-strong
    accentGridLine: 'rgba(56, 189, 248, 0.08)', // from src/apps/trafalgar/web/dashboard/static/dashboard.css: tbody hover background
  },
  radii: {
    xs: '8px', // from src/apps/perona/web/dashboard/static/dashboard.css: .wrangler-close border-radius
    sm: '10px', // from src/apps/trafalgar/web/dashboard/static/dashboard.css: .dashboard-nav a border-radius
    md: '12px', // from src/apps/web_theme/static/theme.css: button/input border-radius
    lg: '16px', // from src/apps/trafalgar/web/dashboard/static/dashboard.css: .dashboard-nav border-radius
    xl: '22px', // from src/apps/trafalgar/web/dashboard/static/dashboard.css: .hero-card border-radius
  },
  spacing: {
    xs: '0.35rem', // from src/apps/web_theme/static/theme.css: .badge padding-y
    sm: '0.6rem', // from src/apps/web_theme/static/theme.css: button/input padding-y
    md: '0.75rem', // from src/apps/trafalgar/web/dashboard/static/dashboard.css: .dashboard-nav padding-y
    lg: '1rem', // from src/apps/web_theme/static/theme.css: .stat-card padding-y baseline
    xl: '1.5rem', // from src/apps/perona/web/dashboard/static/dashboard.css: header/main padding blocks
  },
  shadow: {
    card: '0 20px 40px rgba(8, 15, 35, 0.45)', // from src/apps/web_theme/static/theme.css: --op-shadow
    elevated: '0 20px 40px rgba(8, 15, 35, 0.45)', // shared with card shadow token
    focusRing: '0 0 0 3px rgba(56, 189, 248, 0.18)', // from src/apps/web_theme/static/theme.css: input:focus
  },
  typography: {
    fontFamily: "'Inter', 'Segoe UI', system-ui, -apple-system, BlinkMacSystemFont, sans-serif", // from src/apps/web_theme/static/theme.css: --op-font
    fontSizeBase: '16px', // inferred base size used across dashboards
    fontSizeSm: '0.95rem', // from src/apps/uta/static/control_center.css: header.app-header p font-size
    fontSizeLg: '1.15rem', // from src/apps/perona/web/dashboard/static/dashboard.css: .wrangler-menu-title font-size
    fontWeightRegular: 400,
    fontWeightMedium: 600, // medium emphasis used for nav links and filters
    fontWeightBold: 700,
  },
};

export const roleColors = {
  background: designTokens.colors.background,
  surface: designTokens.colors.surface,
  surfaceMuted: designTokens.colors.surfaceAlt,
  textPrimary: designTokens.colors.text,
  textSecondary: designTokens.colors.textMuted,
  accent: designTokens.colors.primary,
  danger: designTokens.colors.danger,
  warning: designTokens.colors.warning,
  success: designTokens.colors.success,
};

export type RoleColors = typeof roleColors;
