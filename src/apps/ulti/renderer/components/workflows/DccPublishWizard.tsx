import React, { useMemo, useState } from 'react';
import { Button, Card, Modal, StatusBadge, TextInput, useToast } from '../ui';
import { useTheme } from '../../styles/ThemeContext';
import { useHelpContext } from '../HelpContext';

type EnabledDcc = 'maya' | 'blender' | 'unreal';

interface DccPublishWizardProps {
  project?: { name: string; path: string };
  enabledDccs: EnabledDcc[];
  onClose(): void;
}

type PreflightStatus = 'idle' | 'running' | 'success' | 'error';
type PublishStatus = 'idle' | 'running' | 'success' | 'error';

interface PreflightCollection {
  label: string;
  items: string[];
}

interface PreflightResult {
  collections: PreflightCollection[];
  issues: string[];
  warnings: string[];
  rawOutput?: string;
  stderr?: string;
  error?: string;
}

interface PublishOutput {
  stdout: string;
  stderr: string;
  error?: string;
}

const steps = ['Choose DCC & scene', 'Validate publish', 'Run publish'];

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

function parsePreflight(stdout: string): PreflightResult {
  const result: PreflightResult = { collections: [], issues: [], warnings: [], rawOutput: stdout };

  try {
    const parsed = JSON.parse(stdout);
    const collections: PreflightCollection[] = [];

    if (Array.isArray(parsed.cameras)) {
      collections.push({ label: 'Cameras', items: parsed.cameras });
    }
    if (Array.isArray(parsed.references)) {
      collections.push({ label: 'Referenced assets', items: parsed.references });
    }
    if (Array.isArray(parsed.missingTextures)) {
      collections.push({ label: 'Missing textures', items: parsed.missingTextures });
    }

    const warnings: string[] = Array.isArray(parsed.warnings)
      ? parsed.warnings
      : typeof parsed.warnings === 'string'
        ? [parsed.warnings]
        : [];
    const issues: string[] = Array.isArray(parsed.issues)
      ? parsed.issues
      : typeof parsed.issues === 'string'
        ? [parsed.issues]
        : [];

    if (collections.length) {
      result.collections = collections;
    }
    if (issues.length) {
      result.issues = issues;
    }
    if (warnings.length) {
      result.warnings = warnings;
    }

    return result;
  } catch (error) {
    const lowerLines = stdout
      .split('\n')
      .map((line) => line.trim())
      .filter(Boolean);

    result.issues = lowerLines.filter((line) => /error|missing|fail/i.test(line));
    result.warnings = lowerLines.filter((line) => /warn|issue|todo/i.test(line));

    return result;
  }
}

function DccPublishWizard({ project, enabledDccs, onClose }: DccPublishWizardProps): JSX.Element {
  const theme = useTheme();
  const { showToast } = useToast();

  const [currentStep, setCurrentStep] = useState(0);
  const [dccType, setDccType] = useState<EnabledDcc | ''>(enabledDccs[0] ?? '');
  const [scenePath, setScenePath] = useState('');
  const [shotSelection, setShotSelection] = useState('');
  const [preflightStatus, setPreflightStatus] = useState<PreflightStatus>('idle');
  const [preflightResult, setPreflightResult] = useState<PreflightResult>({ collections: [], issues: [], warnings: [] });
  const [publishStatus, setPublishStatus] = useState<PublishStatus>('idle');
  const [publishOutput, setPublishOutput] = useState<PublishOutput>({ stdout: '', stderr: '' });
  const [publishLevel, setPublishLevel] = useState<'work-in-progress' | 'client-ready'>('work-in-progress');
  const [overwriteStrategy, setOverwriteStrategy] = useState<'safe' | 'overwrite'>('safe');
  const [showLogs, setShowLogs] = useState(false);

  useHelpContext(currentStep === 1 ? 'wizard.dccPublish.preflight' : null);

  const canProceed = useMemo(() => Boolean(dccType && scenePath.trim()), [dccType, scenePath]);
  const hasIssues = preflightResult.issues.length > 0;
  const hasWarnings = preflightResult.warnings.length > 0;

  const resetAndClose = (): void => {
    setCurrentStep(0);
    setPreflightStatus('idle');
    setPublishStatus('idle');
    setPreflightResult({ collections: [], issues: [], warnings: [] });
    setPublishOutput({ stdout: '', stderr: '' });
    onClose();
  };

  const handleRunPreflight = async (): Promise<void> => {
    if (!project?.path) {
      setPreflightStatus('error');
      setPreflightResult((prev) => ({ ...prev, error: 'Select a project to continue.' }));
      return;
    }

    setCurrentStep(1);
    setPreflightStatus('running');
    setPreflightResult({ collections: [], issues: [], warnings: [] });

    try {
      // TODO: integrate with final CLI endpoint if signature changes.
      const result = await window.electron.invoke<{ code: number; stdout: string; stderr: string }>('python/run-command', {
        args: ['-m', 'onepiece', 'dcc', 'publish-preflight', '--dcc', dccType, '--scene', scenePath, '--project-root', project.path],
      });

      const parsed = parsePreflight(result.stdout);
      setPreflightResult({
        ...parsed,
        stderr: result.stderr,
        error: result.code === 0 ? undefined : `Preflight exited with code ${result.code}`,
      });
      setPreflightStatus(result.code === 0 ? 'success' : 'error');
    } catch (error) {
      setPreflightStatus('error');
      setPreflightResult({
        collections: [],
        issues: [],
        warnings: [],
        error:
          error instanceof Error
            ? error.message
            : 'Preflight failed. TODO: connect to publish-preflight CLI once available.',
      });
    }
  };

  const handleRunPublish = async (): Promise<void> => {
    if (!project?.path) {
      return;
    }

    setPublishStatus('running');
    setPublishOutput({ stdout: '', stderr: '' });

    try {
      const result = await window.electron.invoke<{ code: number; stdout: string; stderr: string }>('python/run-command', {
        args: ['-m', 'onepiece', 'dcc', 'publish', '--dcc', dccType, '--scene', scenePath, '--project-root', project.path],
      });

      const isSuccess = result.code === 0;
      setPublishStatus(isSuccess ? 'success' : 'error');
      setPublishOutput({
        stdout: result.stdout,
        stderr: result.stderr,
        error: isSuccess ? undefined : `Publish exited with code ${result.code}`,
      });

      if (isSuccess) {
        showToast({ kind: 'success', message: 'DCC publish started' });
      }
    } catch (error) {
      setPublishStatus('error');
      setPublishOutput({
        stdout: '',
        stderr: '',
        error: error instanceof Error ? error.message : 'Failed to run publish.',
      });
    }
  };

  const renderSelectionStep = (): JSX.Element => (
    <div style={{ display: 'grid', gap: theme.spacing.md }}>
      <div style={{ display: 'grid', gap: theme.spacing.xs }}>
        <label style={{ display: 'grid', gap: '0.35rem' }}>
          <span style={{ fontWeight: theme.typography.fontWeightMedium }}>Digital content creation tool</span>
          <select
            value={dccType}
            onChange={(event) => setDccType(event.target.value as EnabledDcc)}
            style={{
              padding: `${theme.spacing.sm} ${theme.spacing.md}`,
              borderRadius: theme.radii.md,
              border: `1px solid ${theme.colors.border}`,
              background: theme.colors.surfaceAlt,
            }}
          >
            <option value="">Select DCC</option>
            {enabledDccs.map((dcc) => (
              <option key={dcc} value={dcc}>
                {dcc.charAt(0).toUpperCase() + dcc.slice(1)}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div style={{ display: 'grid', gap: theme.spacing.xs }}>
        <TextInput
          label="Scene file"
          placeholder="/path/to/scene (file picker coming soon)"
          value={scenePath}
          onChange={(event) => setScenePath(event.target.value)}
          required
        />
        <Button variant="secondary" onClick={() => null} disabled style={{ justifySelf: 'start' }}>
          Browse…
        </Button>
      </div>

      <div style={{ display: 'grid', gap: theme.spacing.xs }}>
        <TextInput
          label="Shot / Sequence"
          placeholder="Optional — select shot once project-info API is available"
          value={shotSelection}
          onChange={(event) => setShotSelection(event.target.value)}
          description="TODO: Pull shot/sequence structure from project-info API."
        />
      </div>
    </div>
  );

  const renderPreflightStep = (): JSX.Element => (
    <div style={{ display: 'grid', gap: theme.spacing.md }}>
      <Card>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div style={{ display: 'grid', gap: '0.35rem' }}>
            <strong>Preflight summary</strong>
            <p style={{ margin: 0, color: theme.colors.textMuted }}>
              {preflightStatus === 'running'
                ? 'Running preflight…'
                : preflightResult.error
                  ? preflightResult.error
                  : hasIssues
                    ? 'Issues detected during preflight.'
                    : 'Ready to publish.'}
            </p>
          </div>
          <StatusBadge
            status={preflightStatus === 'success' && !hasIssues ? 'success' : 'warning'}
            text={hasIssues ? 'Issues' : preflightStatus === 'running' ? 'Running' : 'Ready'}
          />
        </div>
      </Card>

      {preflightResult.collections.length ? (
        <Card title="Detected items">
          <div style={{ display: 'grid', gap: theme.spacing.sm }}>
            {preflightResult.collections.map((collection) => (
              <div key={collection.label} style={{ display: 'grid', gap: '0.35rem' }}>
                <span style={{ fontWeight: theme.typography.fontWeightMedium }}>{collection.label}</span>
                <div style={{ display: 'grid', gap: theme.spacing.xs }}>
                  {collection.items.map((item) => (
                    <label key={`${collection.label}-${item}`} style={{ display: 'flex', gap: theme.spacing.sm }}>
                      <input type="checkbox" defaultChecked />
                      <span>{item}</span>
                    </label>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </Card>
      ) : null}

      {hasWarnings || hasIssues ? (
        <Card title="Issues & warnings">
          <div style={{ display: 'grid', gap: theme.spacing.xs }}>
            {preflightResult.warnings.map((warning) => (
              <p key={warning} style={{ margin: 0, color: theme.colors.textMuted }}>
                ⚠️ {warning}
              </p>
            ))}
            {preflightResult.issues.map((issue) => (
              <p key={issue} style={{ margin: 0, color: theme.colors.danger }}>
                ❗ {issue}
              </p>
            ))}
            {!preflightResult.warnings.length && !preflightResult.issues.length ? (
              <p style={{ margin: 0, color: theme.colors.textMuted }}>No issues detected.</p>
            ) : null}
          </div>
        </Card>
      ) : null}
    </div>
  );

  const renderPublishStep = (): JSX.Element => (
    <div style={{ display: 'grid', gap: theme.spacing.md }}>
      <Card title="Publish options">
        <div style={{ display: 'grid', gap: theme.spacing.sm }}>
          <label style={{ display: 'grid', gap: '0.35rem' }}>
            <span style={{ fontWeight: theme.typography.fontWeightMedium }}>Publish level</span>
            <select
              value={publishLevel}
              onChange={(event) => setPublishLevel(event.target.value as typeof publishLevel)}
              style={{
                padding: `${theme.spacing.sm} ${theme.spacing.md}`,
                borderRadius: theme.radii.md,
                border: `1px solid ${theme.colors.border}`,
                background: theme.colors.surfaceAlt,
              }}
            >
              <option value="work-in-progress">Work-in-progress</option>
              <option value="client-ready">Client-ready</option>
            </select>
          </label>

          <label style={{ display: 'grid', gap: '0.35rem' }}>
            <span style={{ fontWeight: theme.typography.fontWeightMedium }}>Overwrite strategy</span>
            <select
              value={overwriteStrategy}
              onChange={(event) => setOverwriteStrategy(event.target.value as typeof overwriteStrategy)}
              style={{
                padding: `${theme.spacing.sm} ${theme.spacing.md}`,
                borderRadius: theme.radii.md,
                border: `1px solid ${theme.colors.border}`,
                background: theme.colors.surfaceAlt,
              }}
            >
              <option value="safe">Safe (no overwrite)</option>
              <option value="overwrite">Overwrite existing versions</option>
            </select>
          </label>
        </div>
      </Card>

      <Card title="Run status">
        <div style={{ display: 'grid', gap: theme.spacing.sm }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div>
              <p style={{ margin: 0, color: theme.colors.textMuted }}>
                {publishStatus === 'running'
                  ? 'Publishing…'
                  : publishStatus === 'success'
                    ? 'Publish completed.'
                    : publishStatus === 'error'
                      ? publishOutput.error ?? 'Publish reported issues.'
                      : 'Ready to publish.'}
              </p>
            </div>
            <StatusBadge
              status={publishStatus === 'success' ? 'success' : publishStatus === 'error' ? 'warning' : 'info'}
              text={publishStatus === 'running' ? 'Running' : publishStatus === 'success' ? 'Success' : 'Pending'}
            />
          </div>

          <Button variant="secondary" onClick={() => setShowLogs((prev) => !prev)}>
            {showLogs ? 'Hide logs' : 'Show logs'}
          </Button>

          {showLogs ? (
            <div
              style={{
                background: theme.colors.surfaceAlt,
                border: `1px solid ${theme.colors.border}`,
                borderRadius: theme.radii.md,
                padding: theme.spacing.sm,
                maxHeight: '240px',
                overflow: 'auto',
                display: 'grid',
                gap: theme.spacing.sm,
              }}
            >
              <div>
                <h4 style={{ margin: 0 }}>Stdout</h4>
                <pre style={{ margin: 0 }}>{publishOutput.stdout || 'No output yet.'}</pre>
              </div>
              {publishOutput.stderr ? (
                <div>
                  <h4 style={{ margin: 0 }}>Stderr</h4>
                  <pre style={{ margin: 0 }}>{publishOutput.stderr}</pre>
                </div>
              ) : null}
              {publishOutput.error ? (
                <div>
                  <h4 style={{ margin: 0 }}>Error</h4>
                  <p style={{ margin: 0 }}>{publishOutput.error}</p>
                </div>
              ) : null}
            </div>
          ) : null}
        </div>
      </Card>
    </div>
  );

  const renderStep = (): JSX.Element => {
    switch (currentStep) {
      case 0:
        return renderSelectionStep();
      case 1:
        return renderPreflightStep();
      case 2:
        return renderPublishStep();
      default:
        return renderSelectionStep();
    }
  };

  const primaryAction = useMemo(() => {
    if (currentStep === 0) {
      return {
        label: preflightStatus === 'running' ? 'Running preflight…' : 'Next',
        onClick: () => void handleRunPreflight(),
        disabled: !canProceed || preflightStatus === 'running',
        isLoading: preflightStatus === 'running',
      } as const;
    }

    if (currentStep === 1) {
      return {
        label: 'Continue',
        onClick: () => setCurrentStep(2),
        disabled: preflightStatus === 'running',
      } as const;
    }

    return {
      label: publishStatus === 'running' ? 'Publishing…' : 'Publish',
      onClick: () => void handleRunPublish(),
      disabled: publishStatus === 'running',
      isLoading: publishStatus === 'running',
    } as const;
  }, [canProceed, currentStep, preflightStatus, publishStatus]);

  const secondaryAction = useMemo(() => {
    if (currentStep === 0) {
      return { label: 'Cancel', onClick: resetAndClose, variant: 'secondary' } as const;
    }

    return { label: 'Back', onClick: () => setCurrentStep((step) => Math.max(0, step - 1)), variant: 'secondary' } as const;
  }, [currentStep]);

  return (
    <Modal
      isOpen
      onClose={resetAndClose}
      title="DCC Publish"
      description="Guide a DCC scene through preflight and publish commands."
      primaryAction={primaryAction}
      secondaryAction={secondaryAction}
    >
      <div style={{ display: 'grid', gap: theme.spacing.lg }}>
        <StepIndicator currentStep={currentStep} />
        {renderStep()}
      </div>
    </Modal>
  );
}

export default DccPublishWizard;
