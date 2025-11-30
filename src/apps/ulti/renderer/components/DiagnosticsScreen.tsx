import React, { useEffect, useMemo, useState } from 'react';

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

declare global {
  interface Window {
    electron: {
      invoke: <T = unknown>(channel: string, payload?: unknown) => Promise<T>;
    };
  }
}

function DiagnosticsScreen(): JSX.Element {
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

  const statusColor = useMemo(() => {
    if (doctorStatus === 'running') {
      return '#f59e0b';
    }
    if (doctorStatus === 'success') {
      return '#10b981';
    }
    if (doctorStatus === 'failure') {
      return '#ef4444';
    }
    return '#6b7280';
  }, [doctorStatus]);

  const handleRunDoctor = async (): Promise<void> => {
    setDoctorResult((prev) => ({ ...prev, running: true, error: undefined }));
    setCopyMessage('');

    try {
      const result = await window.electron.invoke<{ code: number; stdout: string; stderr: string }>(
        'python/run-command',
        { args: ['-m', 'onepiece', 'doctor'] },
      );

      setDoctorResult({
        running: false,
        exitCode: result.code,
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

  if (loading) {
    return <div className="op-loading">Loading diagnostics...</div>;
  }

  return (
    <div className="diagnostics-screen" style={{ padding: '24px', color: '#111827' }}>
      <h1>Diagnostics</h1>

      <section style={{ marginTop: '16px' }}>
        <h2>Configuration overview</h2>
        <div style={{ display: 'grid', gridTemplateColumns: '200px 1fr', rowGap: '8px', columnGap: '12px' }}>
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
      </section>

      <section style={{ marginTop: '24px' }}>
        <h2>Environment detection</h2>
        <div style={{ display: 'grid', gridTemplateColumns: '200px 1fr', rowGap: '8px', columnGap: '12px' }}>
          <div>Python path guess</div>
          <div>{detectedEnv?.pythonPathGuess ?? 'Not detected'}</div>

          <div>Maya</div>
          <div>{detectedEnv?.dccs?.maya ?? 'Not detected'}</div>

          <div>Blender</div>
          <div>{detectedEnv?.dccs?.blender ?? 'Not detected'}</div>

          <div>Unreal</div>
          <div>{detectedEnv?.dccs?.unreal ?? 'Not detected'}</div>
        </div>
      </section>

      <section style={{ marginTop: '24px' }}>
        <h2>OnePiece doctor</h2>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '12px' }}>
          <button onClick={() => void handleRunDoctor()} disabled={doctorResult.running}>
            {doctorResult.running ? 'Running...' : 'Run full diagnostics'}
          </button>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span
              style={{
                display: 'inline-block',
                width: '12px',
                height: '12px',
                borderRadius: '9999px',
                backgroundColor: statusColor,
              }}
            />
            <span>
              {doctorStatus === 'idle'
                ? 'Not run yet'
                : doctorStatus === 'running'
                  ? 'Running diagnostics...'
                  : doctorStatus === 'success'
                    ? 'Checks passed'
                    : 'Issues detected'}
            </span>
          </div>
          {doctorResult.exitCode !== null && <div>Exit code: {doctorResult.exitCode}</div>}
          {doctorResult.error && <div style={{ color: '#b91c1c' }}>{doctorResult.error}</div>}
        </div>

        <div style={{ marginBottom: '12px' }}>
          <button onClick={() => setShowStdout((prev) => !prev)} style={{ marginRight: '8px' }}>
            {showStdout ? 'Hide' : 'Show'} stdout
          </button>
          <button onClick={() => setShowStderr((prev) => !prev)}>
            {showStderr ? 'Hide' : 'Show'} stderr
          </button>
        </div>

        {showStdout && (
          <div style={{ marginBottom: '12px' }}>
            <h3>stdout</h3>
            <pre
              style={{
                background: '#f3f4f6',
                padding: '12px',
                borderRadius: '6px',
                maxHeight: '240px',
                overflow: 'auto',
                whiteSpace: 'pre-wrap',
              }}
            >
              {doctorResult.stdout || 'No output yet.'}
            </pre>
          </div>
        )}

        {showStderr && (
          <div style={{ marginBottom: '12px' }}>
            <h3>stderr</h3>
            <pre
              style={{
                background: '#fef2f2',
                padding: '12px',
                borderRadius: '6px',
                maxHeight: '240px',
                overflow: 'auto',
                whiteSpace: 'pre-wrap',
              }}
            >
              {doctorResult.stderr || 'No errors reported.'}
            </pre>
          </div>
        )}
      </section>

      <div style={{ marginTop: '24px', display: 'flex', alignItems: 'center', gap: '12px' }}>
        <button onClick={() => void copySummary()}>Copy diagnostics summary</button>
        {copyMessage && <span>{copyMessage}</span>}
      </div>
    </div>
  );
}

export default DiagnosticsScreen;
