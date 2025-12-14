import React, { useEffect, useMemo, useState } from 'react';
import { Button, Card, SectionHeader, StatusBadge } from './ui';
import { useTheme } from '../styles/ThemeContext';
import EnvProfileTool from './tools/EnvProfileTool';

type ProfileOption = 'vfx' | 'archviz' | 'freelancer' | 'demo';

type DccAppKey = 'maya' | 'blender' | 'unreal';

type DccConfig = {
  enabled: boolean;
  executablePath?: string;
};

type DesktopConfig = {
  hasCompletedWizard: boolean;
  createdAt: string;
  updatedAt: string;
  profile?: ProfileOption;
  pythonPath?: string;
  projectRoot?: string;
  shotgrid?: {
    url?: string;
    scriptName?: string;
    apiKey?: string;
  };
  aws?: {
    accessKeyId?: string;
    secretAccessKey?: string;
    region?: string;
    defaultBucket?: string;
  };
  dccs?: Partial<Record<DccAppKey, DccConfig>>;
  services?: {
    profiles: {
      key: string;
      name: string;
      description: string;
      args: string[];
      persistent?: boolean;
    }[];
    enabled?: Record<string, boolean>;
  };
};

type DetectedEnv = {
  pythonPathGuess?: string;
  dccs: Partial<Record<DccAppKey, string>>;
};

type DoctorResult = {
  running: boolean;
  exitCode: number | null;
  stdout: string;
  stderr: string;
  error?: string;
};

function DiagnosticsScreen(): JSX.Element {
  const theme = useTheme();
  const [config, setConfig] = useState<DesktopConfig | null>(null);
  const [detectedEnv, setDetectedEnv] = useState<DetectedEnv | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [doctorResult, setDoctorResult] = useState<DoctorResult>({
    running: false,
    exitCode: null,
    stdout: '',
    stderr: '',
  });
  const [copyMessage, setCopyMessage] = useState<string>('');
  const [showStdout, setShowStdout] = useState<boolean>(true);
  const [showStderr, setShowStderr] = useState<boolean>(false);

  useEffect(() => {
    let isMounted = true;

    const fetchInitialData = async (): Promise<void> => {
      try {
        const [loadedConfig, envDetection] = await Promise.all([
          window.electron.invoke<DesktopConfig>('config/get'),
          window.electron.invoke<DetectedEnv>('system/detect-env'),
        ]);

        if (!isMounted) {
          return;
        }

        setConfig(loadedConfig);
        setDetectedEnv(envDetection);
      } catch (error) {
        console.error('Failed to load diagnostics data', error);
      } finally {
        if (isMounted) {
          setLoading(false);
        }
      }
    };

    void fetchInitialData();

    return () => {
      isMounted = false;
    };
  }, []);

  const shotgridConfigured = useMemo(
    () => Boolean(config?.shotgrid && Object.values(config.shotgrid).some(Boolean)),
    [config?.shotgrid],
  );

  const awsConfigured = useMemo(
    () => Boolean(config?.aws && Object.values(config.aws).some(Boolean)),
    [config?.aws],
  );

  const doctorStatus = useMemo(() => {
    if (doctorResult.running) {
      return 'running';
    }

    if (doctorResult.exitCode === null) {
      return 'idle';
    }

    if (doctorResult.exitCode === 0) {
      return 'success';
    }

    return 'failure';
  }, [doctorResult.exitCode, doctorResult.running]);

  const doctorLabel = useMemo(() => {
    if (doctorStatus === 'idle') return 'Not run yet';
    if (doctorStatus === 'running') return 'Running diagnostics...';
    if (doctorStatus === 'success') return 'Checks passed';
    return 'Issues detected';
  }, [doctorStatus]);

  const confettiPieces = useMemo(
    () =>
      Array.from({ length: 12 }).map((_, index) => ({
        left: `${(index / 12) * 100}%`,
        delay: `${index * 40}ms`,
        rotation: `${(index % 6) * 12 - 30}deg`,
      })),
    [],
  );

  const handleRunDoctor = async (): Promise<void> => {
    setDoctorResult((prev) => ({ ...prev, running: true, error: undefined }));
    setCopyMessage('');

    try {
      const result = await window.electron.invoke<{ exitCode: number; stdout: string; stderr: string }>(
        'python/run-doctor',
      );

      setDoctorResult({
        running: false,
        exitCode: result.exitCode,
        stdout: result.stdout ?? '',
        stderr: result.stderr ?? '',
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to run diagnostics';
      setDoctorResult({ running: false, exitCode: null, stdout: '', stderr: '', error: message });
    }
  };

  const copySummary = async (): Promise<void> => {
    const summary = [
      '# Diagnostics summary',
      '',
      '## Configuration overview',
      `- Profile: ${config?.profile ?? 'Not set'}`,
      `- Project root: ${config?.projectRoot ?? 'Not set'}`,
      `- Python path: ${config?.pythonPath ?? 'Not set'}`,
      `- ShotGrid configured: ${shotgridConfigured ? 'Yes' : 'No'}`,
      `- AWS configured: ${awsConfigured ? 'Yes' : 'No'}`,
      '',
      '## Environment detection',
      `- Python path guess: ${detectedEnv?.pythonPathGuess ?? 'Not detected'}`,
      `- Maya: ${detectedEnv?.dccs?.maya ?? 'Not detected'}`,
      `- Blender: ${detectedEnv?.dccs?.blender ?? 'Not detected'}`,
      `- Unreal: ${detectedEnv?.dccs?.unreal ?? 'Not detected'}`,
      '',
      '## OnePiece doctor',
      `- Exit code: ${
        doctorResult.exitCode === null ? 'Not run yet' : doctorResult.exitCode === 0 ? '0 (success)' : doctorResult.exitCode
      }`,
    ].join('\n');

    try {
      await navigator.clipboard.writeText(summary);
      setCopyMessage('Diagnostics summary copied to clipboard.');
    } catch (error) {
      console.error('Failed to copy diagnostics summary', error);
      setCopyMessage('Unable to copy diagnostics summary.');
    }
  };

  const renderConfigValue = (value: string | undefined): string => value || 'Not set';
  const summaryGridStyle = {
    display: 'grid',
    gridTemplateColumns: '200px 1fr',
    rowGap: '8px',
    columnGap: theme.spacing.md,
  } as const;

  if (loading) {
    return <div className="op-loading">Loading diagnostics...</div>;
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: theme.spacing.lg }}>
      <SectionHeader
        title="Diagnostics"
        subtitle="Inspect your configuration, environment detection, and OnePiece doctor output."
      />

      <Card>
        <SectionHeader title="Configuration overview" />
        <div style={summaryGridStyle}>
          <div>Profile</div>
          <div>{config?.profile ?? 'Not set'}</div>

          <div>Project root</div>
          <div>{renderConfigValue(config?.projectRoot)}</div>

          <div>Python path</div>
          <div>{renderConfigValue(config?.pythonPath)}</div>

          <div>ShotGrid configured</div>
          <div>{shotgridConfigured ? 'Yes' : 'No'}</div>

          <div>AWS configured</div>
          <div>{awsConfigured ? 'Yes' : 'No'}</div>
        </div>
      </Card>

      <Card>
        <SectionHeader title="Environment detection" />
        <div style={summaryGridStyle}>
          <div>Python path guess</div>
          <div>{detectedEnv?.pythonPathGuess ?? 'Not detected'}</div>

          <div>Maya</div>
          <div>{detectedEnv?.dccs?.maya ?? 'Not detected'}</div>

          <div>Blender</div>
          <div>{detectedEnv?.dccs?.blender ?? 'Not detected'}</div>

          <div>Unreal</div>
          <div>{detectedEnv?.dccs?.unreal ?? 'Not detected'}</div>
        </div>
      </Card>

      <EnvProfileTool />

      <Card>
        <SectionHeader
          title="OnePiece doctor"
          subtitle="Run the doctor command to collect stdout and stderr diagnostics."
          action={
            <Button onClick={() => void handleRunDoctor()} isLoading={doctorResult.running} disabled={doctorResult.running}>
              {doctorResult.running ? 'Running…' : 'Run full diagnostics'}
            </Button>
          }
        />
        <div style={{ display: 'flex', alignItems: 'center', gap: theme.spacing.md, marginBottom: theme.spacing.sm }}>
          <StatusBadge status={doctorStatus}>{doctorLabel}</StatusBadge>
          {doctorResult.exitCode !== null && <div>Exit code: {doctorResult.exitCode}</div>}
          {doctorResult.error && <div style={{ color: theme.colors.danger }}>{doctorResult.error}</div>}
        </div>

        {doctorStatus === 'success' ? (
          <div
            style={{
              position: 'relative',
              padding: theme.spacing.sm,
              borderRadius: theme.radii.md,
              background: theme.colors.primarySoft,
              border: `1px solid ${theme.colors.borderStrong}`,
              overflow: 'hidden',
            }}
          >
            <style>{`
              @keyframes op-confetti-fall {
                0% { opacity: 0; transform: translateY(-6px) rotate(var(--rotation, 0deg)); }
                25% { opacity: 1; }
                100% { opacity: 0; transform: translateY(22px) rotate(var(--rotation, 0deg)); }
              }
            `}</style>
            <p style={{ margin: 0, fontWeight: theme.typography.fontWeightMedium }}>
              You're ready to run a show with OnePiece 🎉
            </p>
            <p style={{ margin: '0.2rem 0 0', color: theme.colors.textMuted }}>
              Nice work—your environment checks came back green.
            </p>
            <div aria-hidden style={{ position: 'absolute', inset: 0, pointerEvents: 'none' }}>
              {confettiPieces.map((piece, index) => (
                <span
                  key={piece.left + index}
                  style={{
                    position: 'absolute',
                    left: piece.left,
                    top: '-4px',
                    width: '6px',
                    height: '12px',
                    borderRadius: theme.radii.xs,
                    background: index % 2 === 0 ? theme.colors.success : theme.colors.info,
                    opacity: 0.95,
                    animation: 'op-confetti-fall 1s ease-out',
                    animationDelay: piece.delay,
                    transform: `rotate(${piece.rotation})`,
                  }}
                />
              ))}
            </div>
          </div>
        ) : null}

        <div style={{ marginBottom: theme.spacing.sm, display: 'flex', gap: theme.spacing.sm }}>
          <Button variant="ghost" size="sm" onClick={() => setShowStdout((prev) => !prev)}>
            {showStdout ? 'Hide' : 'Show'} stdout
          </Button>
          <Button variant="ghost" size="sm" onClick={() => setShowStderr((prev) => !prev)}>
            {showStderr ? 'Hide' : 'Show'} stderr
          </Button>
        </div>

        {showStdout && (
          <div style={{ marginBottom: theme.spacing.sm }}>
            <h3 style={{ margin: '0 0 0.35rem' }}>stdout</h3>
            <pre
              style={{
                background: theme.colors.surfaceAlt,
                padding: theme.spacing.md,
                borderRadius: theme.radii.md,
                maxHeight: '240px',
                overflow: 'auto',
                whiteSpace: 'pre-wrap',
                border: `1px solid ${theme.colors.border}`,
              }}
            >
              {doctorResult.stdout || 'No output yet.'}
            </pre>
          </div>
        )}

        {showStderr && (
          <div style={{ marginBottom: theme.spacing.sm }}>
            <h3 style={{ margin: '0 0 0.35rem' }}>stderr</h3>
            <pre
              style={{
                background: theme.colors.surfaceAlt,
                padding: theme.spacing.md,
                borderRadius: theme.radii.md,
                maxHeight: '240px',
                overflow: 'auto',
                whiteSpace: 'pre-wrap',
                border: `1px solid ${theme.colors.border}`,
              }}
            >
              {doctorResult.stderr || 'No errors reported.'}
            </pre>
          </div>
        )}
      </Card>

      <div style={{ display: 'flex', alignItems: 'center', gap: theme.spacing.sm }}>
        <Button variant="secondary" onClick={() => void copySummary()}>
          Copy diagnostics summary
        </Button>
        {copyMessage && <span style={{ color: theme.colors.textMuted }}>{copyMessage}</span>}
      </div>
    </div>
  );
}

export default DiagnosticsScreen;
