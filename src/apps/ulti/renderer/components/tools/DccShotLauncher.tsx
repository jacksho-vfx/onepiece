import React, { useMemo, useRef, useState } from 'react';
import { Button, TextInput, useToast } from '../ui';
import { useTheme } from '../../styles/ThemeContext';

type DccOption = 'auto' | 'maya' | 'blender' | 'unreal';

export type ShotReference = {
  id?: string;
  name: string;
  scenePath: string;
  description?: string;
};

type DccShotLauncherProps = {
  project?: { name: string; path: string } | null;
  shots?: ShotReference[];
};

type CommandResult = { code: number; stdout: string; stderr: string };

function DccShotLauncher({ project, shots = [] }: DccShotLauncherProps): JSX.Element {
  const theme = useTheme();
  const { showToast } = useToast();
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const [scenePath, setScenePath] = useState('');
  const [dcc, setDcc] = useState<DccOption>('auto');
  const [selectedShotId, setSelectedShotId] = useState('');
  const [status, setStatus] = useState<'idle' | 'running' | 'success' | 'error'>('idle');
  const [result, setResult] = useState<CommandResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const stderrTail = useMemo(() => {
    if (!result?.stderr) {
      return '';
    }

    const lines = result.stderr.split('\n').filter(Boolean);
    return lines.slice(Math.max(0, lines.length - 6)).join('\n');
  }, [result]);

  const handleShotSelect = (shotId: string): void => {
    setSelectedShotId(shotId);
    const selectedShot = shots.find((shot) => (shot.id ?? shot.name) === shotId);
    if (selectedShot) {
      setScenePath(selectedShot.scenePath);
    }
  };

  const handleBrowseScene = (): void => {
    fileInputRef.current?.click();
  };

  const handleFilePicked = (event: React.ChangeEvent<HTMLInputElement>): void => {
    const file = event.target.files?.[0];
    if (file) {
      setScenePath((file as unknown as { path?: string }).path ?? file.name);
      setSelectedShotId('');
    }

    // Reset the value so the same file can be re-selected later.
    event.target.value = '';
  };

  const handleLaunch = async (): Promise<void> => {
    if (!scenePath.trim()) {
      setError('Provide a scene path to continue.');
      return;
    }

    setStatus('running');
    setError(null);
    setResult(null);

    const payload: { scenePath: string; dcc?: string } = { scenePath: scenePath.trim() };
    if (dcc !== 'auto') {
      payload.dcc = dcc;
    }

    try {
      const response = await window.electron.invoke<CommandResult>('onepiece/dcc-open-shot', payload);
      setResult(response);

      if (response.code === 0) {
        setStatus('success');
        showToast({ kind: 'success', message: 'Launched scene in DCC' });
      } else {
        setStatus('error');
        setError(`Open shot exited with code ${response.code}.`);
      }
    } catch (err) {
      setStatus('error');
      setError(err instanceof Error ? err.message : 'Failed to launch shot in DCC.');
    }
  };

  return (
    <div style={{ display: 'grid', gap: theme.spacing.md }}>
      {project ? (
        <div className="op-muted" style={{ fontSize: theme.typography.fontSizeSm }}>
          Target project: <strong>{project.name}</strong> ({project.path})
        </div>
      ) : (
        <p className="op-muted" style={{ margin: 0 }}>
          Select a project to pre-populate scene locations (optional).
        </p>
      )}

      {shots.length > 0 ? (
        <label style={{ display: 'grid', gap: '0.35rem' }}>
          <span style={{ fontWeight: theme.typography.fontWeightMedium }}>Known shots</span>
          <select
            value={selectedShotId}
            onChange={(event) => handleShotSelect(event.target.value)}
            style={{
              padding: `${theme.spacing.sm} ${theme.spacing.md}`,
              borderRadius: theme.radii.md,
              border: `1px solid ${theme.colors.border}`,
              background: theme.colors.surfaceAlt,
            }}
          >
            <option value="">Select a shot (optional)</option>
            {shots.map((shot) => {
              const value = shot.id ?? shot.name;
              return (
                <option key={value} value={value}>
                  {shot.name}
                </option>
              );
            })}
          </select>
          <span style={{ color: theme.colors.textMuted, fontSize: theme.typography.fontSizeSm }}>
            Choosing a shot will fill the scene path automatically.
          </span>
        </label>
      ) : null}

      <div style={{ display: 'grid', gap: theme.spacing.xs }}>
        <TextInput
          label="Scene path"
          placeholder="/path/to/scene.ext"
          value={scenePath}
          onChange={(event) => setScenePath(event.target.value)}
          errorText={error && !scenePath.trim() ? 'Scene path is required.' : undefined}
        />
        <div style={{ display: 'flex', gap: theme.spacing.sm }}>
          <Button variant="secondary" onClick={handleBrowseScene} style={{ justifyContent: 'center' }}>
            Browse…
          </Button>
          <input
            ref={fileInputRef}
            type="file"
            style={{ display: 'none' }}
            onChange={handleFilePicked}
          />
          <select
            value={dcc}
            onChange={(event) => setDcc(event.target.value as DccOption)}
            style={{
              padding: `${theme.spacing.sm} ${theme.spacing.md}`,
              borderRadius: theme.radii.md,
              border: `1px solid ${theme.colors.border}`,
              background: theme.colors.surfaceAlt,
              minWidth: '160px',
            }}
            aria-label="Choose DCC"
          >
            <option value="auto">DCC: Auto-detect</option>
            <option value="maya">DCC: Maya</option>
            <option value="blender">DCC: Blender</option>
            <option value="unreal">DCC: Unreal</option>
          </select>
        </div>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: theme.spacing.sm }}>
        <Button isLoading={status === 'running'} onClick={() => void handleLaunch()}>
          Open shot
        </Button>
        {status === 'running' ? <span className="op-muted">Launching in background…</span> : null}
        {status === 'success' ? <span style={{ color: theme.colors.success }}>Ready!</span> : null}
      </div>

      {status === 'error' && error ? (
        <div
          style={{
            padding: theme.spacing.sm,
            borderRadius: theme.radii.md,
            border: `1px solid ${theme.colors.danger}`,
            background: theme.colors.surface,
          }}
        >
          <p style={{ margin: 0, color: theme.colors.danger, fontWeight: theme.typography.fontWeightSemiBold }}>
            {error}
          </p>
          {stderrTail ? (
            <pre
              style={{
                margin: `${theme.spacing.xs} 0 0`,
                padding: theme.spacing.sm,
                background: theme.colors.surfaceAlt,
                borderRadius: theme.radii.sm,
                border: `1px solid ${theme.colors.border}`,
                maxHeight: 180,
                overflow: 'auto',
              }}
            >
              {stderrTail}
            </pre>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

export default DccShotLauncher;
