import React, { useEffect, useMemo, useState } from 'react';
import { Card, Modal, TextInput, useToast } from '../ui';
import { useTheme } from '../../styles/ThemeContext';

interface VendorIngestWizardProps {
  project?: { name: string; path: string };
  onClose(): void;
}

interface DesktopConfig {
  quickActionPresets?: {
    [projectName: string]: {
      vendorIngest?: { sourcePath?: string };
    };
  };
}

interface PreflightIssue {
  level: 'warning' | 'error';
  message: string;
}

interface PreflightResult {
  fileCount?: number;
  issues: PreflightIssue[];
  rawOutput?: string;
  stderr?: string;
  error?: string;
}

const steps = ['Source folder', 'Preflight', 'Run ingest'];

function StepIndicator({ currentStep }: { currentStep: number }): JSX.Element {
  const theme = useTheme();

  return (
    <ol
      aria-label="Wizard steps"
      style={{
        listStyle: 'none',
        padding: 0,
        margin: 0,
        display: 'grid',
        gridTemplateColumns: `repeat(${steps.length}, minmax(0, 1fr))`,
        gap: theme.spacing.sm,
      }}
    >
      {steps.map((label, index) => {
        const isActive = index === currentStep;
        const isComplete = index < currentStep;
        const indicatorColor = isActive
          ? theme.colors.primary
          : isComplete
            ? theme.colors.text
            : theme.colors.textMuted;

        return (
          <li
            key={label}
            style={{
              display: 'grid',
              gap: '0.35rem',
              alignItems: 'center',
              textAlign: 'center',
            }}
          >
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: theme.spacing.xs,
                color: indicatorColor,
                fontWeight: isActive ? theme.typography.fontWeightBold : theme.typography.fontWeightMedium,
                fontSize: theme.typography.fontSizeSm,
                letterSpacing: '0.02em',
              }}
            >
              <span
                aria-hidden
                style={{
                  width: '10px',
                  height: '10px',
                  borderRadius: '999px',
                  background: indicatorColor,
                  boxShadow: isActive ? theme.shadow.card : undefined,
                }}
              />
              <span style={{ opacity: isActive || isComplete ? 1 : 0.8 }}>{label}</span>
            </div>
            <div
              aria-hidden
              style={{
                height: '4px',
                width: '100%',
                borderRadius: theme.radii.xs,
                background: isActive
                  ? theme.colors.primary
                  : isComplete
                    ? theme.colors.borderStrong
                    : theme.colors.border,
                opacity: isActive ? 1 : 0.8,
              }}
            />
          </li>
        );
      })}
    </ol>
  );
}

function parsePreflight(stdout: string): { fileCount?: number; issues: PreflightIssue[] } {
  const fileCountMatch = stdout.match(/(\d+)\s+(?:files?|items?)/i);
  const fileCount = fileCountMatch ? Number(fileCountMatch[1]) : undefined;

  const issues: PreflightIssue[] = stdout
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const lower = line.toLowerCase();

      if (lower.includes('error') || lower.includes('fail') || lower.includes('missing')) {
        return { level: 'error', message: line } as PreflightIssue;
      }

      if (lower.includes('warning') || lower.includes('warn') || lower.includes('issue')) {
        return { level: 'warning', message: line } as PreflightIssue;
      }

      return null;
    })
    .filter((value): value is PreflightIssue => Boolean(value));

  return { fileCount, issues };
}

function VendorIngestWizard({ project, onClose }: VendorIngestWizardProps): JSX.Element {
  const theme = useTheme();
  const { showToast } = useToast();
  const [currentStep, setCurrentStep] = useState(0);
  const [sourcePath, setSourcePath] = useState('');
  const [sourceError, setSourceError] = useState<string | null>(null);
  const [presetSource, setPresetSource] = useState<string | null>(null);
  const [preflightStatus, setPreflightStatus] = useState<'idle' | 'running' | 'success' | 'error'>('idle');
  const [preflightResult, setPreflightResult] = useState<PreflightResult>({ issues: [] });
  const [ingestStatus, setIngestStatus] = useState<'idle' | 'running' | 'success' | 'error'>('idle');
  const [ingestOutput, setIngestOutput] = useState<{ stdout: string; stderr: string; error?: string }>(
    {
      stdout: '',
      stderr: '',
    },
  );

  useEffect(() => {
    if (!project?.name) {
      return;
    }

    let isMounted = true;

    const loadPreset = async (): Promise<void> => {
      try {
        const config = await window.electron.invoke<DesktopConfig>('config/get');
        if (!isMounted || !config?.quickActionPresets?.[project.name]?.vendorIngest) {
          return;
        }

        const presetValue = config.quickActionPresets[project.name].vendorIngest?.sourcePath ?? null;
        setPresetSource(presetValue);
        setSourcePath((prev) => prev || presetValue || '');
      } catch (error) {
        console.error('Failed to load vendor ingest preset', error);
      }
    };

    void loadPreset();

    return () => {
      isMounted = false;
    };
  }, [project?.name]);

  useEffect(() => {
    if (sourceError && sourcePath.trim()) {
      setSourceError(null);
    }
  }, [sourceError, sourcePath]);

  const handleStartPreflight = async (): Promise<void> => {
    if (!sourcePath.trim()) {
      setSourceError('Please provide a source folder path.');
      return;
    }

    if (!project?.path) {
      setSourceError('Select a project to continue.');
      return;
    }

    setCurrentStep(1);
    setPreflightStatus('running');
    setPreflightResult({ issues: [] });

    try {
      const result = await window.electron.invoke<{ code: number; stdout: string; stderr: string }>(
        'python/run-command',
        { args: ['-m', 'onepiece', 'ingest-preflight', '--source', sourcePath, '--project-root', project.path] },
      );

      const parsed = parsePreflight(result.stdout);
      setPreflightResult({
        ...parsed,
        rawOutput: result.stdout,
        stderr: result.stderr,
        error: result.code === 0 ? undefined : `Preflight exited with code ${result.code}`,
      });
      setPreflightStatus(result.code === 0 ? 'success' : 'error');
    } catch (error) {
      setPreflightStatus('error');
      setPreflightResult({ issues: [], error: error instanceof Error ? error.message : 'Preflight failed.' });
    }
  };

  const hasSevereIssues = useMemo(
    () => preflightResult.issues.some((issue) => issue.level === 'error'),
    [preflightResult.issues],
  );

  const preflightSummary = useMemo(() => {
    if (preflightStatus === 'running') {
      return 'Running preflight checks…';
    }

    if (preflightStatus === 'error') {
      return preflightResult.error ?? 'Preflight reported issues.';
    }

    const issueCount = preflightResult.issues.length;
    const fileCountText = preflightResult.fileCount ? `${preflightResult.fileCount} files scanned` : 'Files scanned';

    if (issueCount === 0) {
      return `${fileCountText} — no issues found.`;
    }

    const warnings = preflightResult.issues.filter((issue) => issue.level === 'warning').length;
    const errors = preflightResult.issues.filter((issue) => issue.level === 'error').length;

    const pieces: string[] = [];
    if (warnings) {
      pieces.push(`${warnings} warning${warnings === 1 ? '' : 's'}`);
    }
    if (errors) {
      pieces.push(`${errors} error${errors === 1 ? '' : 's'}`);
    }

    return `${fileCountText} — ${pieces.join(' and ')}`;
  }, [preflightResult.error, preflightResult.fileCount, preflightResult.issues, preflightStatus]);

  const handleConfirmIngest = async (): Promise<void> => {
    if (!project?.path) {
      return;
    }

    setIngestStatus('running');
    setIngestOutput({ stdout: '', stderr: '' });

    try {
      const result = await window.electron.invoke<{ code: number; stdout: string; stderr: string }>('python/run-command', {
        args: ['-m', 'onepiece', 'ingest', '--source', sourcePath, '--project-root', project.path],
      });

      const isSuccess = result.code === 0;
      setIngestStatus(isSuccess ? 'success' : 'error');
      setIngestOutput({
        stdout: result.stdout,
        stderr: result.stderr,
        error: isSuccess ? undefined : `Ingest exited with code ${result.code}`,
      });

      if (isSuccess) {
        showToast({ kind: 'success', message: 'Vendor ingest completed' });
      }
    } catch (error) {
      setIngestStatus('error');
      setIngestOutput({ stdout: '', stderr: '', error: error instanceof Error ? error.message : 'Failed to run ingest.' });
    }
  };

  const renderSourceStep = (): JSX.Element => (
    <div style={{ display: 'grid', gap: theme.spacing.sm }}>
      <TextInput
        label="Source folder"
        placeholder="/path/to/vendor/drop (folder picker coming soon)"
        value={sourcePath}
        onChange={(event) => setSourcePath(event.target.value)}
        required
        error={sourceError ?? undefined}
      />
      {project?.name ? (
        <Card title="Project preset" subtitle={`Saved for ${project.name}`}>
          {presetSource ? (
            <p style={{ margin: 0 }}>Last used source: {presetSource}</p>
          ) : (
            <p style={{ margin: 0, color: theme.colors.textMuted }}>No saved source path for this project yet.</p>
          )}
        </Card>
      ) : null}
    </div>
  );

  const renderPreflightStep = (): JSX.Element => (
    <div style={{ display: 'grid', gap: theme.spacing.md }}>
      <Card>
        <div style={{ display: 'grid', gap: '0.35rem' }}>
          <div style={{ display: 'flex', gap: theme.spacing.sm, alignItems: 'center' }}>
            <span
              aria-hidden
              style={{
                width: '10px',
                height: '10px',
                borderRadius: '999px',
                background:
                  preflightStatus === 'success'
                    ? theme.colors.success
                    : preflightStatus === 'running'
                      ? theme.colors.info
                      : theme.colors.danger,
              }}
            />
            <strong>{preflightStatus === 'success' ? 'Preflight completed' : 'Preflight'}</strong>
          </div>
          <p style={{ margin: 0, color: theme.colors.textMuted }}>{preflightSummary}</p>
        </div>
      </Card>

      {preflightStatus === 'running' ? <p style={{ margin: 0 }}>Running checks…</p> : null}

      {preflightResult.issues.length ? (
        <Card title="Detected issues">
          <ul style={{ margin: 0, paddingLeft: '1.2rem', display: 'grid', gap: '0.35rem' }}>
            {preflightResult.issues.map((issue, index) => (
              <li key={`${issue.level}-${index}`} style={{ color: issue.level === 'error' ? theme.colors.danger : undefined }}>
                <span style={{ fontWeight: theme.typography.fontWeightMedium, textTransform: 'capitalize' }}>
                  {issue.level}
                </span>
                : {issue.message}
              </li>
            ))}
          </ul>
          {hasSevereIssues ? (
            <p style={{ margin: '0.5rem 0 0', color: theme.colors.danger }}>
              Fix the errors above or go back to adjust the source before ingesting.
            </p>
          ) : null}
        </Card>
      ) : null}

      {preflightResult.rawOutput ? (
        <details>
          <summary style={{ cursor: 'pointer' }}>View raw preflight output</summary>
          <pre
            style={{
              marginTop: theme.spacing.sm,
              padding: theme.spacing.sm,
              background: theme.colors.surfaceAlt,
              borderRadius: theme.radii.sm,
              border: `1px solid ${theme.colors.border}`,
              maxHeight: '320px',
              overflow: 'auto',
            }}
          >
            {preflightResult.rawOutput}
          </pre>
          {preflightResult.stderr ? (
            <pre
              style={{
                marginTop: theme.spacing.sm,
                padding: theme.spacing.sm,
                background: theme.colors.surfaceAlt,
                borderRadius: theme.radii.sm,
                border: `1px solid ${theme.colors.border}`,
                maxHeight: '320px',
                overflow: 'auto',
              }}
            >
              {preflightResult.stderr}
            </pre>
          ) : null}
        </details>
      ) : null}
    </div>
  );

  const renderConfirmStep = (): JSX.Element => (
    <div style={{ display: 'grid', gap: theme.spacing.md }}>
      <Card title="Ready to ingest">
        <dl className="op-definition-list">
          <div>
            <dt>Project</dt>
            <dd>{project?.name ?? 'Unknown project'}</dd>
          </div>
          <div>
            <dt>Project path</dt>
            <dd>{project?.path ?? 'N/A'}</dd>
          </div>
          <div>
            <dt>Source</dt>
            <dd>{sourcePath}</dd>
          </div>
          <div>
            <dt>Preflight</dt>
            <dd>{preflightSummary}</dd>
          </div>
        </dl>
      </Card>

      <Card title="Ingest status">
        {ingestStatus === 'idle' ? <p style={{ margin: 0 }}>Ready to start.</p> : null}
        {ingestStatus === 'running' ? <p style={{ margin: 0 }}>Ingest is running…</p> : null}
        {ingestStatus === 'success' ? (
          <p style={{ margin: 0, color: theme.colors.success }}>Ingest completed successfully.</p>
        ) : null}
        {ingestStatus === 'error' ? (
          <p style={{ margin: 0, color: theme.colors.danger }}>{ingestOutput.error ?? 'Ingest failed.'}</p>
        ) : null}

        {ingestOutput.stdout ? (
          <div style={{ marginTop: theme.spacing.sm }}>
            <h4 style={{ margin: '0 0 0.25rem' }}>Stdout</h4>
            <pre
              style={{
                background: theme.colors.surfaceAlt,
                padding: theme.spacing.sm,
                borderRadius: theme.radii.sm,
                maxHeight: '220px',
                overflow: 'auto',
                margin: 0,
                border: `1px solid ${theme.colors.border}`,
              }}
            >
              {ingestOutput.stdout}
            </pre>
          </div>
        ) : null}

        {ingestOutput.stderr ? (
          <div style={{ marginTop: theme.spacing.sm }}>
            <h4 style={{ margin: '0 0 0.25rem' }}>Stderr</h4>
            <pre
              style={{
                background: theme.colors.surfaceAlt,
                padding: theme.spacing.sm,
                borderRadius: theme.radii.sm,
                maxHeight: '220px',
                overflow: 'auto',
                margin: 0,
                border: `1px solid ${theme.colors.border}`,
              }}
            >
              {ingestOutput.stderr}
            </pre>
          </div>
        ) : null}
      </Card>
    </div>
  );

  const primaryAction = useMemo(() => {
    switch (currentStep) {
      case 0:
        return {
          label: 'Run preflight',
          onClick: () => void handleStartPreflight(),
          disabled: !sourcePath.trim() || !project?.path,
        };
      case 1:
        if (preflightStatus === 'running') {
          return {
            label: 'Running…',
            onClick: () => undefined,
            disabled: true,
          };
        }

        return {
          label: 'Continue to ingest',
          onClick: () => setCurrentStep(2),
          disabled: preflightStatus !== 'success' || hasSevereIssues,
        };
      case 2:
      default:
        if (ingestStatus === 'success') {
          return { label: 'Close', onClick: onClose };
        }

        return {
          label: ingestStatus === 'running' ? 'Running…' : 'Run ingest',
          onClick: () => void handleConfirmIngest(),
          disabled: ingestStatus === 'running',
          isLoading: ingestStatus === 'running',
        };
    }
  }, [currentStep, hasSevereIssues, ingestStatus, onClose, preflightStatus, project?.path, sourcePath]);

  const secondaryAction = useMemo(() => {
    if (currentStep === 0) {
      return { label: 'Cancel', onClick: onClose, variant: 'secondary' as const };
    }

    return {
      label: 'Back',
      onClick: () => setCurrentStep((prev) => Math.max(0, prev - 1)),
      variant: 'secondary' as const,
      disabled: preflightStatus === 'running' || ingestStatus === 'running',
    };
  }, [currentStep, ingestStatus, onClose, preflightStatus]);

  const renderStepContent = (): JSX.Element => {
    switch (currentStep) {
      case 0:
        return renderSourceStep();
      case 1:
        return renderPreflightStep();
      case 2:
      default:
        return renderConfirmStep();
    }
  };

  return (
    <Modal
      isOpen
      onClose={onClose}
      title="Vendor ingest"
      description="Validate a drop folder, review warnings, and ingest into your project."
      primaryAction={primaryAction}
      secondaryAction={secondaryAction}
    >
      <div style={{ display: 'grid', gap: theme.spacing.lg }}>
        <StepIndicator currentStep={currentStep} />
        {renderStepContent()}
      </div>
    </Modal>
  );
}

export default VendorIngestWizard;
