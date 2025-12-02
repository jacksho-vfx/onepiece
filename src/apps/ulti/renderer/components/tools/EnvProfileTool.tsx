import React, { useMemo, useState } from 'react';
import { Button, Card, SectionHeader, StatusBadge, useToast } from '../ui';
import { useTheme } from '../../styles/ThemeContext';

type CommandResult = { code: number; stdout: string; stderr: string };

type EnvCheckState = {
  running: boolean;
  result: CommandResult | null;
  hint?: string | null;
  error?: string | null;
};

type ProfileState = {
  running: boolean;
  result: CommandResult | null;
  formattedOutput: string;
  error?: string | null;
};

function deriveHint(stderr: string): string | null {
  const normalized = stderr.toLowerCase();

  if (normalized.includes('shotgrid')) {
    return 'ShotGrid credentials may be missing or incorrect.';
  }

  if (normalized.includes('aws') || normalized.includes('s3')) {
    return 'AWS credentials or the default bucket might not be configured yet.';
  }

  if (normalized.includes('profile') && normalized.includes('not found')) {
    return 'The requested profile could not be resolved. Check your onepiece.toml and selected profile.';
  }

  if (normalized.includes('dcc')) {
    return 'A DCC executable was not detected. Verify your DCC paths in the setup wizard.';
  }

  return null;
}

function formatProfileOutput(output: string): string {
  const trimmed = output.trim();
  if (!trimmed) {
    return 'No profile output yet.';
  }

  try {
    const parsed = JSON.parse(trimmed);
    return JSON.stringify(parsed, null, 2);
  } catch {
    // Not JSON, fall back to original text
  }

  return trimmed;
}

function EnvProfileTool(): JSX.Element {
  const theme = useTheme();
  const { showToast } = useToast();

  const [envCheck, setEnvCheck] = useState<EnvCheckState>({ running: false, result: null });
  const [profileState, setProfileState] = useState<ProfileState>({
    running: false,
    result: null,
    formattedOutput: 'Run the profile resolution to see output.',
  });
  const [showLogs, setShowLogs] = useState(false);

  const envStatus = useMemo(() => {
    if (!envCheck.result) {
      return 'Idle';
    }
    return envCheck.result.code === 0 ? 'Success' : 'Failed';
  }, [envCheck.result]);

  const runEnvironmentCheck = async (): Promise<void> => {
    setEnvCheck((prev) => ({ ...prev, running: true, error: null }));

    try {
      const result = await window.electron.invoke<CommandResult>('onepiece/info', { checkIntegrations: true });
      const hint = result.code === 0 ? null : deriveHint(result.stderr || result.stdout);

      setEnvCheck({ running: false, result, hint });
      setShowLogs(true);

      if (result.code === 0) {
        showToast({ kind: 'success', message: 'Environment check completed' });
      } else {
        showToast({ kind: 'error', message: 'Environment check failed – see details below.' });
      }
    } catch (error) {
      setEnvCheck({
        running: false,
        result: null,
        error: 'Failed to run environment check. Please try again.',
      });
      showToast({ kind: 'error', message: 'Environment check failed – see details below.' });
    }
  };

  const runProfileResolution = async (): Promise<void> => {
    setProfileState((prev) => ({ ...prev, running: true, error: null }));

    try {
      const result = await window.electron.invoke<CommandResult>('onepiece/profile', { showSources: true });
      setProfileState({
        running: false,
        result,
        formattedOutput: formatProfileOutput(result.stdout || result.stderr),
      });
      showToast({ kind: 'success', message: 'Resolved profile sources' });
    } catch (error) {
      setProfileState((prev) => ({
        ...prev,
        running: false,
        error: 'Failed to resolve profile. Review your configuration and try again.',
      }));
      showToast({ kind: 'error', message: 'Failed to resolve profile' });
    }
  };

  return (
    <Card>
      <div style={{ display: 'grid', gap: theme.spacing.lg }}>
        <SectionHeader
          title="Environment & Profile"
          subtitle="Run quick CLI-based checks to validate your workstation and profile resolution."
        />

        <div style={{ display: 'grid', gap: theme.spacing.sm }}>
          <header style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div>
              <p className="op-eyebrow">Environment check</p>
              <p style={{ margin: 0, color: theme.colors.textMuted }}>
                Wraps <code>onepiece info --check-integrations</code> to validate DCC detection and integrations.
              </p>
            </div>
            <div style={{ display: 'flex', gap: theme.spacing.sm, alignItems: 'center' }}>
              {envCheck.result ? <StatusBadge status={envStatus}>{envStatus}</StatusBadge> : null}
              <Button onClick={() => void runEnvironmentCheck()} isLoading={envCheck.running}>
                Run environment check
              </Button>
            </div>
          </header>

          {envCheck.error ? <p className="op-error">{envCheck.error}</p> : null}
          {envCheck.hint && envCheck.result && envCheck.result.code !== 0 ? (
            <p style={{ margin: 0, color: theme.colors.warning }}>
              <strong>What might be wrong?</strong> {envCheck.hint}
            </p>
          ) : null}

          {envCheck.result ? (
            <div style={{ display: 'grid', gap: theme.spacing.xs }}>
              <Button variant="ghost" onClick={() => setShowLogs((prev) => !prev)}>
                {showLogs ? 'Hide log output' : 'Show log output'}
              </Button>
              {showLogs ? (
                <div className="op-log-output">
                  {envCheck.result.stdout ? (
                    <div>
                      <h4>Stdout</h4>
                      <pre>{envCheck.result.stdout}</pre>
                    </div>
                  ) : null}
                  {envCheck.result.stderr ? (
                    <div>
                      <h4>Stderr</h4>
                      <pre>{envCheck.result.stderr}</pre>
                    </div>
                  ) : null}
                  {!envCheck.result.stdout && !envCheck.result.stderr ? (
                    <p className="op-muted">No output captured.</p>
                  ) : null}
                </div>
              ) : null}
            </div>
          ) : (
            <p className="op-muted" style={{ margin: 0 }}>
              Run the environment check to view integration status and logs.
            </p>
          )}
        </div>

        <div style={{ display: 'grid', gap: theme.spacing.sm }}>
          <header style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div>
              <p className="op-eyebrow">Profile resolution</p>
              <p style={{ margin: 0, color: theme.colors.textMuted }}>
                Wraps <code>onepiece profile --show-sources</code> to show merged configuration.
              </p>
            </div>
            <Button onClick={() => void runProfileResolution()} isLoading={profileState.running}>
              Show resolved profile
            </Button>
          </header>

          {profileState.error ? <p className="op-error">{profileState.error}</p> : null}

          {profileState.result ? (
            <StatusBadge status={profileState.result.code === 0 ? 'success' : 'error'}>
              {profileState.result.code === 0 ? 'Resolved' : 'Resolution failed'}
            </StatusBadge>
          ) : null}

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
            }}
          >
            {profileState.formattedOutput}
          </pre>
        </div>
      </div>
    </Card>
  );
}

export default EnvProfileTool;
