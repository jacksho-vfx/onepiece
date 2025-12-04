import React, { useMemo, useState } from 'react';
import { Button, Card, SectionHeader, TextInput, useToast } from '../ui';
import { useTheme } from '../../styles/ThemeContext';

interface CommandResult {
  code: number;
  stdout: string;
  stderr: string;
}

function deriveErrorHint(output: string): string | null {
  const normalized = output.toLowerCase();

  if (normalized.includes('maya') || normalized.includes('pymel')) {
    return 'Confirm Maya is installed and PyMEL is available in your Python environment.';
  }

  if (normalized.includes('permission')) {
    return 'Check file permissions for the working scene and output directory.';
  }

  if (normalized.includes('namespace')) {
    return 'Namespace cleanup may require closing the scene and retrying to avoid locked edits.';
  }

  return null;
}

function extractOutputPath(output: string): string | null {
  const pathMatch = output.match(/output\s+path[:\s]+(.+)/i) || output.match(/written\s+to[:\s]+(.+)/i);
  return pathMatch ? pathMatch[1].trim() : null;
}

function AnimationToolsPanel(): JSX.Element {
  const theme = useTheme();
  const { showToast } = useToast();

  const [debugSceneName, setDebugSceneName] = useState('current');
  const [debugState, setDebugState] = useState<{
    running: boolean;
    result: CommandResult | null;
    error: string | null;
  }>({ running: false, result: null, error: null });

  const [cleanupSceneName, setCleanupSceneName] = useState('');
  const [cleanupKeepReferences, setCleanupKeepReferences] = useState(false);
  const [cleanupKeepNamespaces, setCleanupKeepNamespaces] = useState(false);
  const [cleanupState, setCleanupState] = useState<{
    running: boolean;
    result: CommandResult | null;
    error: string | null;
  }>({ running: false, result: null, error: null });

  const [playblastForm, setPlayblastForm] = useState({
    project: '',
    sequence: '',
    shot: '',
    artist: '',
    camera: '',
    version: '',
    outputDirectory: '',
    format: 'mov',
    codec: 'h264',
    width: '1920',
    height: '1080',
    frameStart: '',
    frameEnd: '',
    description: '',
    includeAudio: false,
  });
  const [playblastState, setPlayblastState] = useState<{
    running: boolean;
    result: CommandResult | null;
    error: string | null;
  }>({ running: false, result: null, error: null });

  const debugOutput = useMemo(() => {
    if (!debugState.result) {
      return '';
    }
    return (debugState.result.stdout || debugState.result.stderr || '').trim();
  }, [debugState.result]);

  const playblastOutputPath = useMemo(() => {
    if (!playblastState.result?.stdout) {
      return null;
    }

    return extractOutputPath(playblastState.result.stdout);
  }, [playblastState.result]);

  const handleDebug = async (): Promise<void> => {
    if (!debugSceneName.trim()) {
      setDebugState((prev) => ({ ...prev, error: 'Scene name is required.' }));
      return;
    }

    setDebugState({ running: true, result: null, error: null });

    try {
      const result = await window.electron.invoke<CommandResult>('onepiece/animation-debug', {
        sceneName: debugSceneName.trim(),
      });

      setDebugState({ running: false, result, error: result.code === 0 ? null : 'Debug run reported issues.' });

      if (result.code === 0) {
        showToast({ kind: 'success', message: 'Debug report complete' });
      } else {
        showToast({ kind: 'error', message: 'Debug run completed with warnings' });
      }
    } catch (error) {
      setDebugState({
        running: false,
        result: null,
        error: error instanceof Error ? error.message : 'Failed to run animation debug.',
      });
    }
  };

  const handleCleanup = async (): Promise<void> => {
    if (!cleanupSceneName.trim()) {
      setCleanupState((prev) => ({ ...prev, error: 'Scene name is required.' }));
      return;
    }

    setCleanupState({ running: true, result: null, error: null });

    try {
      const result = await window.electron.invoke<CommandResult>('onepiece/animation-cleanup', {
        sceneName: cleanupSceneName.trim(),
        keepUnusedReferences: cleanupKeepReferences,
        keepNamespaces: cleanupKeepNamespaces,
      });

      setCleanupState({ running: false, result, error: result.code === 0 ? null : 'Cleanup encountered issues.' });

      if (result.code === 0) {
        showToast({ kind: 'success', message: 'Scene cleaned' });
      } else {
        showToast({ kind: 'error', message: 'Cleanup reported issues' });
      }
    } catch (error) {
      setCleanupState({
        running: false,
        result: null,
        error: error instanceof Error ? error.message : 'Failed to clean scene.',
      });
    }
  };

  const handlePlayblast = async (): Promise<void> => {
    const version = Number(playblastForm.version);
    const width = Number(playblastForm.width);
    const height = Number(playblastForm.height);
    const frameStart = playblastForm.frameStart ? Number(playblastForm.frameStart) : null;
    const frameEnd = playblastForm.frameEnd ? Number(playblastForm.frameEnd) : null;

    if (!playblastForm.project || !playblastForm.shot || !playblastForm.artist || !playblastForm.camera) {
      setPlayblastState((prev) => ({ ...prev, error: 'Project, shot, artist, and camera are required.' }));
      return;
    }

    if (!playblastForm.outputDirectory) {
      setPlayblastState((prev) => ({ ...prev, error: 'Output directory is required.' }));
      return;
    }

    if (Number.isNaN(version)) {
      setPlayblastState((prev) => ({ ...prev, error: 'Version must be a number.' }));
      return;
    }

    if (playblastForm.frameStart || playblastForm.frameEnd) {
      if (frameStart === null || frameEnd === null || Number.isNaN(frameStart) || Number.isNaN(frameEnd)) {
        setPlayblastState((prev) => ({ ...prev, error: 'Provide both frame start and end as numbers.' }));
        return;
      }
    }

    setPlayblastState({ running: true, result: null, error: null });

    try {
      const result = await window.electron.invoke<CommandResult>('onepiece/animation-playblast', {
        project: playblastForm.project.trim(),
        sequence: playblastForm.sequence.trim() || undefined,
        shot: playblastForm.shot.trim(),
        artist: playblastForm.artist.trim(),
        camera: playblastForm.camera.trim(),
        version,
        outputDirectory: playblastForm.outputDirectory.trim(),
        format: playblastForm.format.trim() || undefined,
        codec: playblastForm.codec.trim() || undefined,
        width: Number.isNaN(width) ? undefined : width,
        height: Number.isNaN(height) ? undefined : height,
        frameStart: frameStart ?? undefined,
        frameEnd: frameEnd ?? undefined,
        description: playblastForm.description.trim() || undefined,
        includeAudio: playblastForm.includeAudio,
      });

      setPlayblastState({ running: false, result, error: result.code === 0 ? null : 'Playblast failed.' });

      if (result.code === 0) {
        showToast({ kind: 'success', message: 'Playblast generated' });
      } else {
        showToast({ kind: 'error', message: 'Playblast exited with errors' });
      }
    } catch (error) {
      setPlayblastState({
        running: false,
        result: null,
        error: error instanceof Error ? error.message : 'Failed to create playblast.',
      });
    }
  };

  const renderOutput = (title: string, body: string, error?: string | null): JSX.Element | null => {
    if (!body && !error) {
      return null;
    }

    return (
      <div
        style={{
          border: `1px solid ${theme.colors.border}`,
          borderRadius: theme.radii.md,
          padding: theme.spacing.sm,
          background: theme.colors.surface,
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <strong>{title}</strong>
          {error ? <span className="op-error">{error}</span> : null}
        </div>
        {body ? (
          <pre style={{ margin: 0, maxHeight: '200px', overflow: 'auto' }}>
            {body}
          </pre>
        ) : null}
      </div>
    );
  };

  const sectionStyle = {
    display: 'grid',
    gap: theme.spacing.sm,
    padding: theme.spacing.sm,
    borderRadius: theme.radii.lg,
    border: `1px solid ${theme.colors.border}`,
    background: theme.colors.surfaceAlt,
  } as const;

  return (
    <Card>
      <div style={{ display: 'grid', gap: theme.spacing.lg }}>
        <SectionHeader
          title="Animation tools"
          subtitle="Wrap Maya animation debug, cleanup, and playblast helpers without leaving the desktop app."
        />

        <div style={sectionStyle}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div>
              <p className="op-eyebrow">Debug animation</p>
              <p style={{ margin: 0, color: theme.colors.textMuted }}>
                Wraps <code>onepiece dcc animation debug-animation</code> to surface scene issues.
              </p>
            </div>
            <Button isLoading={debugState.running} onClick={() => void handleDebug()}>
              Run debug
            </Button>
          </div>

          <TextInput
            label="Scene name"
            placeholder="seq010_sh010_anim_v003"
            value={debugSceneName}
            onChange={(event) => setDebugSceneName(event.target.value)}
            errorText={debugState.error && !debugSceneName.trim() ? 'Scene name is required.' : undefined}
          />

          {debugState.error && debugSceneName.trim() ? (
            <p className="op-error" style={{ margin: 0 }}>
              {debugState.error}
            </p>
          ) : null}

          {debugState.result?.stderr ? (
            <p style={{ margin: 0, color: theme.colors.warning }}>
              <strong>Hint:</strong> {deriveErrorHint(debugState.result.stderr) ?? 'Review stderr for more details.'}
            </p>
          ) : null}

          {renderOutput('Debug output', debugOutput, null)}
        </div>

        <div style={sectionStyle}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div>
              <p className="op-eyebrow">Cleanup scene</p>
              <p style={{ margin: 0, color: theme.colors.textMuted }}>
                Prune unused references and namespaces with <code>cleanup-scene</code>.
              </p>
            </div>
            <Button isLoading={cleanupState.running} onClick={() => void handleCleanup()}>
              Cleanup scene
            </Button>
          </div>

          <TextInput
            label="Scene name"
            placeholder="seq010_sh010_anim_v003"
            value={cleanupSceneName}
            onChange={(event) => setCleanupSceneName(event.target.value)}
            errorText={cleanupState.error && !cleanupSceneName.trim() ? 'Scene name is required.' : undefined}
          />

          <div style={{ display: 'grid', gap: theme.spacing.xs }}>
            <label style={{ display: 'flex', alignItems: 'center', gap: theme.spacing.xs }}>
              <input
                type="checkbox"
                checked={cleanupKeepReferences}
                onChange={(event) => setCleanupKeepReferences(event.target.checked)}
              />
              <span>Keep unused references</span>
            </label>

            <label style={{ display: 'flex', alignItems: 'center', gap: theme.spacing.xs }}>
              <input
                type="checkbox"
                checked={cleanupKeepNamespaces}
                onChange={(event) => setCleanupKeepNamespaces(event.target.checked)}
              />
              <span>Keep namespaces</span>
            </label>
          </div>

          {cleanupState.error && cleanupSceneName.trim() ? (
            <p className="op-error" style={{ margin: 0 }}>
              {cleanupState.error}
            </p>
          ) : null}

          {cleanupState.result?.stderr ? (
            <p style={{ margin: 0, color: theme.colors.warning }}>
              <strong>Hint:</strong> {deriveErrorHint(cleanupState.result.stderr) ?? 'Review stderr for more details.'}
            </p>
          ) : null}

          {renderOutput('Cleanup output', cleanupState.result?.stdout ?? '', cleanupState.error)}
        </div>

        <div style={sectionStyle}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: theme.spacing.sm }}>
            <div>
              <p className="op-eyebrow">Playblast</p>
              <p style={{ margin: 0, color: theme.colors.textMuted }}>
                Capture preview renders via <code>onepiece dcc animation playblast</code>.
              </p>
            </div>
            <Button isLoading={playblastState.running} onClick={() => void handlePlayblast()}>
              Create playblast
            </Button>
          </div>

          <div style={{
            display: 'grid',
            gap: theme.spacing.sm,
            gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))',
          }}>
            <TextInput
              label="Project"
              value={playblastForm.project}
              onChange={(event) => setPlayblastForm((prev) => ({ ...prev, project: event.target.value }))}
              placeholder="SHOW01"
            />
            <TextInput
              label="Sequence (optional)"
              value={playblastForm.sequence}
              onChange={(event) => setPlayblastForm((prev) => ({ ...prev, sequence: event.target.value }))}
              placeholder="sq010"
            />
            <TextInput
              label="Shot"
              value={playblastForm.shot}
              onChange={(event) => setPlayblastForm((prev) => ({ ...prev, shot: event.target.value }))}
              placeholder="sh010"
            />
            <TextInput
              label="Artist"
              value={playblastForm.artist}
              onChange={(event) => setPlayblastForm((prev) => ({ ...prev, artist: event.target.value }))}
              placeholder="alex.r"
            />
            <TextInput
              label="Camera"
              value={playblastForm.camera}
              onChange={(event) => setPlayblastForm((prev) => ({ ...prev, camera: event.target.value }))}
              placeholder="renderCam"
            />
            <TextInput
              label="Version"
              value={playblastForm.version}
              onChange={(event) => setPlayblastForm((prev) => ({ ...prev, version: event.target.value }))}
              placeholder="12"
            />
            <TextInput
              label="Output directory"
              value={playblastForm.outputDirectory}
              onChange={(event) => setPlayblastForm((prev) => ({ ...prev, outputDirectory: event.target.value }))}
              placeholder="./playblasts/sh010_v012"
            />
            <TextInput
              label="Format"
              value={playblastForm.format}
              onChange={(event) => setPlayblastForm((prev) => ({ ...prev, format: event.target.value }))}
              placeholder="mov"
            />
            <TextInput
              label="Codec"
              value={playblastForm.codec}
              onChange={(event) => setPlayblastForm((prev) => ({ ...prev, codec: event.target.value }))}
              placeholder="h264"
            />
            <TextInput
              label="Width"
              value={playblastForm.width}
              onChange={(event) => setPlayblastForm((prev) => ({ ...prev, width: event.target.value }))}
              placeholder="1920"
            />
            <TextInput
              label="Height"
              value={playblastForm.height}
              onChange={(event) => setPlayblastForm((prev) => ({ ...prev, height: event.target.value }))}
              placeholder="1080"
            />
            <TextInput
              label="Frame start"
              value={playblastForm.frameStart}
              onChange={(event) => setPlayblastForm((prev) => ({ ...prev, frameStart: event.target.value }))}
              placeholder="1001"
            />
            <TextInput
              label="Frame end"
              value={playblastForm.frameEnd}
              onChange={(event) => setPlayblastForm((prev) => ({ ...prev, frameEnd: event.target.value }))}
              placeholder="1120"
            />
            <TextInput
              label="Description"
              value={playblastForm.description}
              onChange={(event) => setPlayblastForm((prev) => ({ ...prev, description: event.target.value }))}
              placeholder="Facial polish preview"
            />
          </div>

          <label style={{ display: 'flex', alignItems: 'center', gap: theme.spacing.xs }}>
            <input
              type="checkbox"
              checked={playblastForm.includeAudio}
              onChange={(event) => setPlayblastForm((prev) => ({ ...prev, includeAudio: event.target.checked }))}
            />
            <span>Include audio</span>
          </label>

          {playblastState.error ? (
            <p className="op-error" style={{ margin: 0 }}>
              {playblastState.error}
            </p>
          ) : null}

          {playblastState.result?.stderr ? (
            <p style={{ margin: 0, color: theme.colors.warning }}>
              <strong>Hint:</strong> {deriveErrorHint(playblastState.result.stderr) ?? 'Review stderr for more details.'}
            </p>
          ) : null}

          {playblastOutputPath ? (
            <p style={{ margin: 0 }}>
              <strong>Output:</strong> {playblastOutputPath}
            </p>
          ) : null}

          {renderOutput('Playblast output', playblastState.result?.stdout ?? '', playblastState.error)}
        </div>
      </div>
    </Card>
  );
}

export default AnimationToolsPanel;
