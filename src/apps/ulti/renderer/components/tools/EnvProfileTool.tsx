import React, { useMemo, useState } from 'react';
import { Button, Card, SectionHeader, StatusBadge, useToast } from '../ui';
import { useTheme } from '../../styles/ThemeContext';

interface SummaryResult {
  exitCode: number;
  stdout: string;
  stderr: string;
}

interface SectionState {
  running: boolean;
  result: SummaryResult | null;
  error?: string | null;
  expanded: boolean;
}

function combineOutput(result: SummaryResult | null): string {
  const stdout = result?.stdout?.trim() ?? '';
  const stderr = result?.stderr?.trim() ?? '';

  if (stdout && stderr) {
    return `${stdout}\n\n[stderr]\n${stderr}`;
  }

  if (stdout) {
    return stdout;
  }

  if (stderr) {
    return stderr;
  }

  return 'No output yet.';
}

function formatProfileText(result: SummaryResult | null): string {
  const preferred = result?.stdout?.trim() || result?.stderr?.trim();
  if (!preferred) {
    return 'Run the profile resolution to see output.';
  }

  try {
    const parsed = JSON.parse(preferred);
    return JSON.stringify(parsed, null, 2);
  } catch {
    // fall back to raw output
  }

  return preferred;
}

function EnvProfileTool(): JSX.Element {
  const theme = useTheme();
  const { showToast } = useToast();

  const [envState, setEnvState] = useState<SectionState>({
    running: false,
    result: null,
    expanded: false,
  });
  const [profileState, setProfileState] = useState<SectionState>({
    running: false,
    result: null,
    expanded: true,
  });

  const envStatus = useMemo(() => {
    if (envState.running) return 'Running';
    if (!envState.result) return 'Idle';
    return envState.result.exitCode === 0 ? 'Success' : 'Error';
  }, [envState.result, envState.running]);

  const envStatusLabel = useMemo(() => {
    if (envState.running) return 'Running';
    if (!envState.result) return 'Not run yet';
    return envState.result.exitCode === 0 ? 'OK' : 'Failed';
  }, [envState.result, envState.running]);

  const profileStatus = useMemo(() => {
    if (profileState.running) return 'Running';
    if (!profileState.result) return 'Idle';
    return profileState.result.exitCode === 0 ? 'Success' : 'Error';
  }, [profileState.result, profileState.running]);

  const profileStatusLabel = useMemo(() => {
    if (profileState.running) return 'Running';
    if (!profileState.result) return 'Not run yet';
    return profileState.result.exitCode === 0 ? 'OK' : 'Failed';
  }, [profileState.result, profileState.running]);

  const runEnvironmentSummary = async (): Promise<void> => {
    setEnvState((prev) => ({ ...prev, running: true, error: null }));

    try {
      const result = await window.electron.invoke<SummaryResult>('onepiece/env-summary');
      setEnvState({ running: false, result, error: null, expanded: true });

      if (result.exitCode === 0) {
        showToast({ kind: 'success', message: 'Environment check completed' });
      } else {
        showToast({ kind: 'error', message: 'Environment check failed – see details below.' });
      }
    } catch (error) {
      setEnvState({
        running: false,
        result: null,
        error: 'Failed to run environment check. Please try again.',
        expanded: false,
      });
      showToast({ kind: 'error', message: 'Environment check failed – see details below.' });
    }
  };

  const runProfileSummary = async (): Promise<void> => {
    setProfileState((prev) => ({ ...prev, running: true, error: null }));

    try {
      const result = await window.electron.invoke<SummaryResult>('onepiece/profile-summary');
      setProfileState({ running: false, result, error: null, expanded: true });
    } catch (error) {
      setProfileState({
        running: false,
        result: null,
        error: 'Failed to resolve profile. Review your configuration and try again.',
        expanded: false,
      });
    }
  };

  return (
    <Card>
      <div style={{ display: 'grid', gap: theme.spacing.lg }}>
        <SectionHeader
          title="Environment & Profile"
          subtitle="Run CLI-powered summaries without opening a terminal."
        />

        <div
          style={{
            display: 'grid',
            gap: theme.spacing.sm,
            padding: theme.spacing.md,
            borderRadius: theme.radii.md,
            border: `1px solid ${theme.colors.border}`,
            background: theme.colors.surfaceAlt,
          }}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: theme.spacing.md }}>
            <div>
              <p className="op-eyebrow" style={{ margin: 0 }}>
                Environment check
              </p>
              <p style={{ margin: 0, color: theme.colors.textMuted }}>
                Use the built-in environment summary command to validate your setup.
              </p>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: theme.spacing.sm }}>
              {envStatusLabel ? <StatusBadge status={envStatus}>{envStatusLabel}</StatusBadge> : null}
              <Button onClick={() => void runEnvironmentSummary()} isLoading={envState.running}>
                Run environment check
              </Button>
            </div>
          </div>

          {envState.error ? <p className="op-error">{envState.error}</p> : null}

          {envState.result ? (
            <div style={{ display: 'grid', gap: theme.spacing.xs }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <p style={{ margin: 0, color: theme.colors.textMuted }}>
                  Exit code: {envState.result.exitCode}
                </p>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setEnvState((prev) => ({ ...prev, expanded: !prev.expanded }))}
                >
                  {envState.expanded ? 'Hide output' : 'Show output'}
                </Button>
              </div>
              {envState.expanded ? (
                <pre
                  style={{
                    margin: 0,
                    padding: theme.spacing.md,
                    background: theme.colors.surfaceMuted,
                    borderRadius: theme.radii.md,
                    border: `1px solid ${theme.colors.border}`,
                    maxHeight: '320px',
                    overflow: 'auto',
                    whiteSpace: 'pre-wrap',
                  }}
                >
                  {combineOutput(envState.result)}
                </pre>
              ) : null}
            </div>
          ) : (
            <p className="op-muted" style={{ margin: 0 }}>
              Run the environment check to view validation output.
            </p>
          )}
        </div>

        <div
          style={{
            display: 'grid',
            gap: theme.spacing.sm,
            padding: theme.spacing.md,
            borderRadius: theme.radii.md,
            border: `1px solid ${theme.colors.border}`,
            background: theme.colors.surfaceAlt,
          }}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: theme.spacing.md }}>
            <div>
              <p className="op-eyebrow" style={{ margin: 0 }}>
                Profile/config
              </p>
              <p style={{ margin: 0, color: theme.colors.textMuted }}>
                View the resolved configuration profile straight from the CLI.
              </p>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: theme.spacing.sm }}>
              {profileStatusLabel ? <StatusBadge status={profileStatus}>{profileStatusLabel}</StatusBadge> : null}
              <Button onClick={() => void runProfileSummary()} isLoading={profileState.running}>
                Show resolved profile
              </Button>
            </div>
          </div>

          {profileState.error ? <p className="op-error">{profileState.error}</p> : null}

          <div style={{ display: 'grid', gap: theme.spacing.xs }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              {profileState.result ? (
                <p style={{ margin: 0, color: theme.colors.textMuted }}>
                  Exit code: {profileState.result.exitCode}
                </p>
              ) : null}
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setProfileState((prev) => ({ ...prev, expanded: !prev.expanded }))}
                disabled={!profileState.result && !profileState.error}
              >
                {profileState.expanded ? 'Hide details' : 'Show details'}
              </Button>
            </div>
            {profileState.expanded ? (
              <pre
                style={{
                  margin: 0,
                  padding: theme.spacing.md,
                  background: theme.colors.surfaceMuted,
                  borderRadius: theme.radii.md,
                  border: `1px solid ${theme.colors.border}`,
                  fontFamily: 'monospace',
                  whiteSpace: 'pre-wrap',
                  wordBreak: 'break-word',
                  maxHeight: '320px',
                  overflow: 'auto',
                }}
              >
                {profileState.error ?? formatProfileText(profileState.result)}
              </pre>
            ) : null}
          </div>
        </div>
      </div>
    </Card>
  );
}

export default EnvProfileTool;
