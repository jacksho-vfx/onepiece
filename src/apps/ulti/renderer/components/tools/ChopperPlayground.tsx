import React, { useMemo, useRef, useState } from 'react';
import { Button, Card, SectionHeader, TextInput, useToast } from '../ui';
import { useTheme } from '../../styles/ThemeContext';

type CommandResult = { code: number; stdout: string; stderr: string };

type InspectSummary = {
  dimensions?: string;
  frames?: number;
  metadata?: string;
};

type RenderResponse = { taskId: string; outputDir: string };

type RenderFormat = 'ppm' | 'png' | 'gif' | 'mp4';

function parseInspectSummary(output: string): InspectSummary | null {
  const trimmed = output.trim();

  if (!trimmed) {
    return null;
  }

  try {
    const parsed = JSON.parse(trimmed) as { width?: number; height?: number; frames?: number; metadata?: unknown };
    const dimensions = parsed.width && parsed.height ? `${parsed.width} x ${parsed.height}` : undefined;
    const frames = typeof parsed.frames === 'number' ? parsed.frames : undefined;
    const metadata = parsed.metadata ? JSON.stringify(parsed.metadata, null, 2) : undefined;

    if (dimensions || frames || metadata) {
      return { dimensions, frames, metadata };
    }
  } catch {
    // Fall back to plain text if the output is not JSON.
  }

  return null;
}

function ChopperPlayground(): JSX.Element {
  const theme = useTheme();
  const { showToast } = useToast();
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const [scenePath, setScenePath] = useState('');
  const [format, setFormat] = useState<RenderFormat>('png');
  const [extraArgs, setExtraArgs] = useState('');
  const [inspectResult, setInspectResult] = useState<CommandResult | null>(null);
  const [inspectError, setInspectError] = useState<string | null>(null);
  const [isInspecting, setIsInspecting] = useState(false);
  const [renderTaskId, setRenderTaskId] = useState<string | null>(null);
  const [isRendering, setIsRendering] = useState(false);

  const inspectSummary = useMemo(() => {
    const output = inspectResult?.stdout || inspectResult?.stderr || '';
    return output ? parseInspectSummary(output) : null;
  }, [inspectResult]);

  const handleBrowseScene = (): void => {
    fileInputRef.current?.click();
  };

  const handleFilePicked = (event: React.ChangeEvent<HTMLInputElement>): void => {
    const file = event.target.files?.[0];
    if (file) {
      setScenePath((file as unknown as { path?: string }).path ?? file.name);
    }

    event.target.value = '';
  };

  const handleInspect = async (): Promise<void> => {
    const trimmedPath = scenePath.trim();
    if (!trimmedPath) {
      setInspectError('Provide a scene path to inspect.');
      return;
    }

    setIsInspecting(true);
    setInspectError(null);
    setInspectResult(null);

    try {
      const result = await window.electron.invoke<CommandResult>('chopper/inspect', { scenePath: trimmedPath });
      setInspectResult(result);
      if (result.code === 0) {
        showToast({ kind: 'success', message: 'Scene inspected' });
      } else {
        showToast({ kind: 'error', message: 'Inspect finished with errors' });
      }
    } catch (error) {
      console.error('Failed to inspect scene', error);
      setInspectError('Unable to inspect this scene. Confirm the path and try again.');
      showToast({ kind: 'error', message: 'Inspect failed' });
    } finally {
      setIsInspecting(false);
    }
  };

  const handleOpenOutputDir = async (targetPath: string): Promise<void> => {
    try {
      await window.electron.invoke('fs/open-in-os', { path: targetPath });
    } catch (err) {
      console.error('Failed to open output folder', err);
      showToast({ kind: 'error', message: 'Unable to open output folder' });
    }
  };

  const handleRender = async (): Promise<void> => {
    const trimmedPath = scenePath.trim();
    if (!trimmedPath) {
      setInspectError('Provide a scene path to render.');
      return;
    }

    setIsRendering(true);
    setInspectError(null);

    const args = extraArgs
      .split(/\s+/)
      .map((arg) => arg.trim())
      .filter(Boolean);

    try {
      const response = await window.electron.invoke<RenderResponse>('chopper/render', {
        scenePath: trimmedPath,
        format,
        extraArgs: args,
      });
      setRenderTaskId(response.taskId);
      showToast({
        kind: 'info',
        message: 'Render started as a background task',
        actionLabel: 'Open output folder',
        onAction: () => void handleOpenOutputDir(response.outputDir),
      });
    } catch (error) {
      console.error('Failed to start render', error);
      showToast({ kind: 'error', message: 'Render failed to start' });
    } finally {
      setIsRendering(false);
    }
  };

  return (
    <Card>
      <div style={{ display: 'grid', gap: theme.spacing.md }}>
        <SectionHeader
          title="Chopper Playground"
          subtitle="Inspect JSON scenes and trigger renders without leaving the desktop."
        />

        <div style={{ display: 'grid', gap: theme.spacing.xs }}>
          <TextInput
            label="Scene path"
            placeholder="/path/to/scene.json"
            value={scenePath}
            onChange={(event) => setScenePath(event.target.value)}
            errorText={inspectError && !scenePath.trim() ? inspectError : undefined}
          />
          <div style={{ display: 'flex', gap: theme.spacing.sm, alignItems: 'center', flexWrap: 'wrap' }}>
            <Button variant="secondary" onClick={handleBrowseScene} style={{ justifyContent: 'center' }}>
              Browse…
            </Button>
            <input
              ref={fileInputRef}
              type="file"
              accept=".json"
              style={{ display: 'none' }}
              onChange={handleFilePicked}
            />
            <label style={{ display: 'grid', gap: theme.spacing.xs }}>
              <span style={{ fontSize: theme.typography.fontSizeSm, color: theme.colors.textMuted }}>Format</span>
              <select
                value={format}
                onChange={(event) => setFormat(event.target.value as RenderFormat)}
                style={{
                  padding: `${theme.spacing.sm} ${theme.spacing.md}`,
                  borderRadius: theme.radii.md,
                  border: `1px solid ${theme.colors.border}`,
                  background: theme.colors.surfaceAlt,
                  minWidth: '140px',
                }}
              >
                <option value="ppm">PPM</option>
                <option value="png">PNG</option>
                <option value="gif">GIF</option>
                <option value="mp4">MP4</option>
              </select>
            </label>
            <div style={{ flex: 1, minWidth: '200px' }}>
              <TextInput
                label="Extra CLI arguments"
                placeholder="--camera main --samples 8"
                value={extraArgs}
                onChange={(event) => setExtraArgs(event.target.value)}
                helperText="Optional flags passed directly to chopper render."
              />
            </div>
          </div>
        </div>

        <div style={{ display: 'flex', gap: theme.spacing.sm, alignItems: 'center', flexWrap: 'wrap' }}>
          <Button onClick={() => void handleInspect()} isLoading={isInspecting}>
            Inspect scene
          </Button>
          <Button variant="secondary" onClick={() => void handleRender()} isLoading={isRendering}>
            Render
          </Button>
          {renderTaskId ? (
            <span style={{ color: theme.colors.textMuted }}>Task ID: {renderTaskId}</span>
          ) : null}
        </div>

        {inspectError && scenePath.trim() ? (
          <p className="op-error" style={{ margin: 0 }}>
            {inspectError}
          </p>
        ) : null}

        {inspectResult ? (
          <div
            style={{
              border: `1px solid ${theme.colors.border}`,
              borderRadius: theme.radii.md,
              background: theme.colors.surfaceAlt,
              padding: theme.spacing.md,
              display: 'grid',
              gap: theme.spacing.sm,
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <h4 style={{ margin: 0 }}>Inspect output</h4>
              <span style={{ color: inspectResult.code === 0 ? theme.colors.success : theme.colors.danger }}>
                Exit code {inspectResult.code}
              </span>
            </div>
            {inspectSummary ? (
              <div style={{ display: 'grid', gap: theme.spacing.xs }}>
                {inspectSummary.dimensions ? (
                  <div>
                    <p className="op-eyebrow" style={{ margin: 0 }}>
                      Dimensions
                    </p>
                    <p style={{ margin: 0 }}>{inspectSummary.dimensions}</p>
                  </div>
                ) : null}
                {typeof inspectSummary.frames === 'number' ? (
                  <div>
                    <p className="op-eyebrow" style={{ margin: 0 }}>
                      Frames
                    </p>
                    <p style={{ margin: 0 }}>{inspectSummary.frames}</p>
                  </div>
                ) : null}
                {inspectSummary.metadata ? (
                  <div>
                    <p className="op-eyebrow" style={{ margin: 0 }}>
                      Metadata
                    </p>
                    <pre style={{ margin: 0, whiteSpace: 'pre-wrap' }}>{inspectSummary.metadata}</pre>
                  </div>
                ) : null}
              </div>
            ) : null}
            <div className="op-log-output">
              {inspectResult.stdout ? (
                <div>
                  <h5 style={{ margin: `0 0 ${theme.spacing.xs}` }}>Stdout</h5>
                  <pre>{inspectResult.stdout || '—'}</pre>
                </div>
              ) : null}
              {inspectResult.stderr ? (
                <div>
                  <h5 style={{ margin: `0 0 ${theme.spacing.xs}` }}>Stderr</h5>
                  <pre>{inspectResult.stderr || '—'}</pre>
                </div>
              ) : null}
              {!inspectResult.stdout && !inspectResult.stderr ? (
                <p className="op-muted" style={{ margin: 0 }}>
                  No output captured.
                </p>
              ) : null}
            </div>
          </div>
        ) : (
          <p className="op-muted" style={{ margin: 0 }}>
            Inspect a scene to view dimensions, frame counts, and raw output.
          </p>
        )}
      </div>
    </Card>
  );
}

export default ChopperPlayground;
