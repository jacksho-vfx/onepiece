import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Button, Card, TextInput, useToast } from '../ui';
import { useTheme } from '../../styles/ThemeContext';

interface PipelineSummary {
  id: string;
  name: string;
  description?: string;
  parameters?: string[];
}

interface ParameterRow {
  key: string;
  value: string;
}

interface PipelineRunnerPanelProps {
  onViewTasks?: () => void;
  initialPipelineId?: string | null;
}

declare global {
  interface Window {
    electron: {
      invoke: <T = unknown>(channel: string, payload?: unknown) => Promise<T>;
    };
  }
}

function PipelineRunnerPanel({ onViewTasks, initialPipelineId }: PipelineRunnerPanelProps): JSX.Element {
  const theme = useTheme();
  const { showToast } = useToast();
  const [pipelines, setPipelines] = useState<PipelineSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedPipelineId, setSelectedPipelineId] = useState<string | null>(initialPipelineId ?? null);
  const [parameterRows, setParameterRows] = useState<ParameterRow[]>([{ key: '', value: '' }]);
  const [running, setRunning] = useState(false);

  const selectedPipeline = useMemo(
    () => pipelines.find((pipeline) => pipeline.id === selectedPipelineId) ?? pipelines[0] ?? null,
    [pipelines, selectedPipelineId],
  );

  useEffect(() => {
    if (selectedPipeline?.id) {
      return;
    }

    if (pipelines.length > 0) {
      setSelectedPipelineId(pipelines[0].id);
    }
  }, [pipelines, selectedPipeline]);

  const fetchPipelines = useCallback(async (): Promise<void> => {
    setLoading(true);
    setError(null);
    try {
      const result = await window.electron.invoke<PipelineSummary[]>('trafalgar/pipeline-list');
      setPipelines(result);
      setSelectedPipelineId((current) => {
        if (result.length === 0) {
          return null;
        }

        if (current && result.some((pipeline) => pipeline.id === current)) {
          return current;
        }

        return result[0].id;
      });
    } catch (err) {
      console.error('Failed to load pipelines', err);
      setError('Unable to load pipelines. Confirm Trafalgar is installed and try again.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchPipelines();
  }, [fetchPipelines]);

  useEffect(() => {
    if (!selectedPipeline) {
      setParameterRows([{ key: '', value: '' }]);
      return;
    }

    setParameterRows((prev) => {
      const existing = new Map(prev.map((row) => [row.key, row.value]));
      const parameterKeys =
        selectedPipeline.parameters && selectedPipeline.parameters.length > 0
          ? selectedPipeline.parameters
          : prev.length > 0
            ? prev.map((row) => row.key)
            : [''];

      const nextRows = parameterKeys.map((key) => ({
        key,
        value: existing.get(key) ?? '',
      }));

      return nextRows.length > 0 ? nextRows : [{ key: '', value: '' }];
    });
  }, [selectedPipeline]);

  const handleParameterChange = (index: number, field: keyof ParameterRow, value: string): void => {
    setParameterRows((prev) => {
      const next = [...prev];
      next[index] = { ...next[index], [field]: value };
      return next;
    });
  };

  const handleAddParameter = (): void => {
    setParameterRows((prev) => [...prev, { key: '', value: '' }]);
  };

  const handleRemoveParameter = (index: number): void => {
    setParameterRows((prev) => (prev.length === 1 ? prev : prev.filter((_, i) => i !== index)));
  };

  const handleRunPipeline = async (): Promise<void> => {
    if (!selectedPipeline) {
      return;
    }

    setRunning(true);
    const parameters = Object.fromEntries(
      parameterRows
        .map(({ key, value }) => ({ key: key.trim(), value }))
        .filter(({ key }) => Boolean(key))
        .map(({ key, value }) => [key, value]),
    );

    try {
      await window.electron.invoke<string>('trafalgar/pipeline-run', {
        pipelineId: selectedPipeline.id,
        parameters,
      });
      showToast({
        kind: 'info',
        message: 'Pipeline run started',
        actionLabel: onViewTasks ? 'View tasks' : undefined,
        onAction: onViewTasks,
      });
    } catch (err) {
      console.error('Failed to start pipeline run', err);
      showToast({ kind: 'error', message: 'Pipeline run failed to start' });
    } finally {
      setRunning(false);
    }
  };

  const renderPipelineRow = (pipeline: PipelineSummary): JSX.Element => {
    const isSelected = pipeline.id === selectedPipeline?.id;
    return (
      <tr
        key={pipeline.id}
        onClick={() => setSelectedPipelineId(pipeline.id)}
        style={{
          cursor: 'pointer',
          background: isSelected ? theme.colors.surfaceMuted : 'transparent',
        }}
      >
        <td style={{ padding: `${theme.spacing.xs} ${theme.spacing.sm}` }}>{pipeline.name}</td>
        <td style={{ padding: `${theme.spacing.xs} ${theme.spacing.sm}`, color: theme.colors.textMuted }}>
          {pipeline.id}
        </td>
        <td style={{ padding: `${theme.spacing.xs} ${theme.spacing.sm}`, color: theme.colors.textMuted }}>
          {pipeline.description || '—'}
        </td>
      </tr>
    );
  };

  return (
    <Card>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h3 style={{ margin: 0 }}>Pipeline Runner</h3>
          <p style={{ margin: 0, color: theme.colors.textMuted }}>
            Inspect Trafalgar pipelines and trigger runs with optional parameters.
          </p>
        </div>
        <Button variant="secondary" onClick={() => void fetchPipelines()} isLoading={loading}>
          Refresh
        </Button>
      </div>

      {error ? <p className="op-error" style={{ marginTop: theme.spacing.sm }}>{error}</p> : null}

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: '2fr 1.2fr',
          gap: theme.spacing.lg,
          marginTop: theme.spacing.md,
        }}
      >
        <div>
          {pipelines.length === 0 && !loading ? (
            <p className="op-muted" style={{ margin: 0 }}>
              No pipelines available. Ensure your profile exposes pipeline definitions.
            </p>
          ) : (
            <div style={{ border: `1px solid ${theme.colors.border}`, borderRadius: theme.radii.md, overflow: 'hidden' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead style={{ background: theme.colors.surfaceMuted }}>
                  <tr>
                    <th style={{ textAlign: 'left', padding: `${theme.spacing.xs} ${theme.spacing.sm}` }}>Name</th>
                    <th style={{ textAlign: 'left', padding: `${theme.spacing.xs} ${theme.spacing.sm}` }}>ID</th>
                    <th style={{ textAlign: 'left', padding: `${theme.spacing.xs} ${theme.spacing.sm}` }}>Description</th>
                  </tr>
                </thead>
                <tbody>
                  {pipelines.map((pipeline) => renderPipelineRow(pipeline))}
                  {loading ? (
                    <tr>
                      <td colSpan={3} style={{ padding: `${theme.spacing.sm} ${theme.spacing.md}` }}>
                        Loading pipelines...
                      </td>
                    </tr>
                  ) : null}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <div
          style={{
            border: `1px solid ${theme.colors.border}`,
            borderRadius: theme.radii.md,
            padding: theme.spacing.md,
            background: theme.colors.surfaceAlt,
            minHeight: '240px',
          }}
        >
          {selectedPipeline ? (
            <div style={{ display: 'grid', gap: theme.spacing.sm }}>
              <div>
                <p className="op-eyebrow">Selected pipeline</p>
                <h4 style={{ margin: '0 0 0.25rem' }}>{selectedPipeline.name}</h4>
                <p style={{ margin: 0, color: theme.colors.textMuted }}>{selectedPipeline.id}</p>
                {selectedPipeline.description ? (
                  <p style={{ margin: `${theme.spacing.xs} 0 0`, color: theme.colors.text }}>{selectedPipeline.description}</p>
                ) : null}
                {selectedPipeline.parameters && selectedPipeline.parameters.length > 0 ? (
                  <p style={{ margin: `${theme.spacing.xs} 0 0`, color: theme.colors.textMuted }}>
                    Expected parameters: {selectedPipeline.parameters.join(', ')}
                  </p>
                ) : (
                  <p style={{ margin: `${theme.spacing.xs} 0 0`, color: theme.colors.textMuted }}>
                    Parameters are optional for this pipeline.
                  </p>
                )}
              </div>

              <div style={{ display: 'grid', gap: theme.spacing.sm }}>
                <p className="op-eyebrow">Parameters</p>
                {parameterRows.map((row, index) => (
                  <div
                    key={`${row.key}-${index}`}
                    style={{ display: 'grid', gridTemplateColumns: '1fr 1fr auto', gap: theme.spacing.sm, alignItems: 'end' }}
                  >
                    <TextInput
                      label="Key"
                      placeholder="profile"
                      value={row.key}
                      onChange={(event) => handleParameterChange(index, 'key', event.target.value)}
                    />
                    <TextInput
                      label="Value"
                      placeholder="episodic"
                      value={row.value}
                      onChange={(event) => handleParameterChange(index, 'value', event.target.value)}
                    />
                    <Button
                      variant="ghost"
                      onClick={() => handleRemoveParameter(index)}
                      disabled={parameterRows.length === 1}
                    >
                      Remove
                    </Button>
                  </div>
                ))}
                <div style={{ display: 'flex', gap: theme.spacing.sm }}>
                  <Button variant="secondary" onClick={handleAddParameter}>
                    Add parameter
                  </Button>
                  <Button
                    onClick={() => void handleRunPipeline()}
                    disabled={!selectedPipeline || running}
                    isLoading={running}
                  >
                    Run pipeline
                  </Button>
                </div>
                <p style={{ margin: 0, color: theme.colors.textMuted }}>
                  Runs are tracked in the Tasks tab. Use parameters to pass context into pipeline steps.
                </p>
              </div>
            </div>
          ) : (
            <p className="op-muted" style={{ margin: 0 }}>
              Select a pipeline to view details and start a run.
            </p>
          )}
        </div>
      </div>
    </Card>
  );
}

export default PipelineRunnerPanel;
