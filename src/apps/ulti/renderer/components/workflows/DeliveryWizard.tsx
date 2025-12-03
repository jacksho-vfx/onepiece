import React, { useMemo, useRef, useState } from 'react';
import { Button, Card, Modal, StatusBadge, TextInput, WizardStep as WizardStepContainer, useToast } from '../ui';
import { useTheme } from '../../styles/ThemeContext';

interface DeliveryWizardProps {
  project?: { name: string; path: string };
  onClose(): void;
  onCompleted?: () => void;
  onOpenShotgridOps?: () => void;
}

type WizardStep = 0 | 1 | 2 | 3;
type PreflightStatus = 'idle' | 'running' | 'success' | 'error';
type DeliveryStatus = 'idle' | 'running' | 'success' | 'error';

type DeliveryType = 'episode' | 'shots' | 'archviz';

interface PreflightResult {
  readyItems: string[];
  missingItems: string[];
  warnings: string[];
  rawOutput?: string;
  error?: string;
}

const steps = ['Select content', 'Choose targets', 'Preflight', 'Run delivery'];

function StepIndicator({ currentStep }: { currentStep: WizardStep }): JSX.Element {
  const theme = useTheme();

  return (
    <div style={{ display: 'grid', gap: theme.spacing.xs }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span style={{ color: theme.colors.textMuted, fontSize: theme.typography.fontSizeSm }}>
          Step {currentStep + 1} of {steps.length}
        </span>
      </div>
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
    </div>
  );
}

function parsePreflight(stdout: string): PreflightResult {
  try {
    const parsed = JSON.parse(stdout);
    const readyItems = Array.isArray(parsed.ready) ? parsed.ready : [];
    const missingItems = Array.isArray(parsed.missing) ? parsed.missing : [];
    const warnings = Array.isArray(parsed.warnings)
      ? parsed.warnings
      : typeof parsed.warnings === 'string'
        ? [parsed.warnings]
        : [];

    return {
      readyItems,
      missingItems,
      warnings,
      rawOutput: stdout,
    };
  } catch (error) {
    const lines = stdout
      .split('\n')
      .map((line) => line.trim())
      .filter(Boolean);

    return {
      readyItems: lines.filter((line) => /ready|ok|complete/i.test(line)),
      missingItems: lines.filter((line) => /missing|not found|failed/i.test(line)),
      warnings: lines.filter((line) => /warn|todo/i.test(line)),
      rawOutput: stdout,
    };
  }
}

function DeliveryWizard({ project, onClose, onCompleted, onOpenShotgridOps }: DeliveryWizardProps): JSX.Element {
  const theme = useTheme();
  const { showToast } = useToast();
  const hasCompletedRef = useRef(false);

  const [currentStep, setCurrentStep] = useState<WizardStep>(0);
  const [deliveryName, setDeliveryName] = useState('');
  const [deliveryType, setDeliveryType] = useState<DeliveryType>('episode');
  const [shotSelection, setShotSelection] = useState('');

  const [includeShotgrid, setIncludeShotgrid] = useState(false);
  const [includeS3Mirror, setIncludeS3Mirror] = useState(false);
  const [includeMediaShuttle, setIncludeMediaShuttle] = useState(false);

  const [shotgridPlaylist, setShotgridPlaylist] = useState('');
  const [s3Path, setS3Path] = useState('');
  const [stagingFolder, setStagingFolder] = useState('');

  const [preflightStatus, setPreflightStatus] = useState<PreflightStatus>('idle');
  const [preflightResult, setPreflightResult] = useState<PreflightResult>({
    readyItems: [],
    missingItems: [],
    warnings: [],
  });
  const [deliveryStatus, setDeliveryStatus] = useState<DeliveryStatus>('idle');
  const [deliveryLogs, setDeliveryLogs] = useState('');

  const projectRoot = project?.path ?? '';
  const hasProject = Boolean(projectRoot);

  const canProceedFromContent = useMemo(
    () => Boolean(deliveryName.trim()) && hasProject,
    [deliveryName, hasProject],
  );

  const canProceedFromTargets = useMemo(() => {
    if (!canProceedFromContent) {
      return false;
    }

    if (!includeShotgrid && !includeS3Mirror && !includeMediaShuttle) {
      return false;
    }

    const shotgridOk = !includeShotgrid || Boolean(shotgridPlaylist.trim());
    const s3Ok = !includeS3Mirror || Boolean(s3Path.trim());
    const stagingOk = !includeMediaShuttle || Boolean(stagingFolder.trim());

    return shotgridOk && s3Ok && stagingOk;
  }, [canProceedFromContent, includeMediaShuttle, includeS3Mirror, includeShotgrid, s3Path, shotgridPlaylist, stagingFolder]);

  const handleResetAndClose = (): void => {
    setCurrentStep(0);
    setPreflightStatus('idle');
    setDeliveryStatus('idle');
    setPreflightResult({ readyItems: [], missingItems: [], warnings: [] });
    setDeliveryLogs('');
    onClose();
  };

  const buildArgs = (command: 'delivery-preflight' | 'delivery'): string[] => {
    const args = ['-m', 'onepiece', command, '--project-root', projectRoot, '--delivery-name', deliveryName];

    if (deliveryType === 'episode') {
      args.push('--type', 'episode');
    } else if (deliveryType === 'shots') {
      args.push('--type', 'shots', '--shots', shotSelection);
    } else if (deliveryType === 'archviz') {
      args.push('--type', 'archviz');
    }

    if (includeShotgrid) {
      args.push('--shotgrid-playlist', shotgridPlaylist);
    }
    if (includeS3Mirror) {
      args.push('--s3-prefix', s3Path);
    }
    if (includeMediaShuttle) {
      args.push('--staging-folder', stagingFolder);
    }

    return args;
  };

  const runPreflight = async (): Promise<void> => {
    if (!hasProject) {
      setPreflightStatus('error');
      showToast({ title: 'Select a project', description: 'Choose a project before running delivery.', variant: 'error' });
      return;
    }

    setPreflightStatus('running');
    setPreflightResult({ readyItems: [], missingItems: [], warnings: [] });

    try {
      const result = await window.electron.invoke<{ code: number; stdout: string; stderr: string }>('python/run-command', {
        args: buildArgs('delivery-preflight'),
      });

      if (result.code !== 0) {
        setPreflightStatus('error');
        setPreflightResult({ readyItems: [], missingItems: [], warnings: [], rawOutput: result.stdout, error: result.stderr });
        showToast({
          title: 'Preflight failed',
          description: result.stderr || `Command exited with code ${result.code}`,
          variant: 'error',
        });
        return;
      }

      const parsed = parsePreflight(result.stdout);

      // TODO: Replace with real delivery preflight CLI that returns JSON with missing renders, mismatched frame ranges, etc.
      setPreflightResult(parsed);
      setPreflightStatus('success');
      setCurrentStep(2);
    } catch (error) {
      console.error('Failed to run delivery preflight', error);
      setPreflightStatus('error');
      setPreflightResult({ readyItems: [], missingItems: [], warnings: [], error: 'Failed to run preflight' });
      showToast({ title: 'Preflight error', description: 'Unable to run delivery preflight.', variant: 'error' });
    }
  };

  const runDelivery = async (): Promise<void> => {
    if (!hasProject) {
      setDeliveryStatus('error');
      showToast({ title: 'Select a project', description: 'Choose a project before running delivery.', variant: 'error' });
      return;
    }

    setDeliveryStatus('running');
    setDeliveryLogs('');

    const handleComplete = (): void => {
      if (hasCompletedRef.current) {
        return;
      }

      hasCompletedRef.current = true;
      onCompleted?.();
    };

    try {
      const result = await window.electron.invoke<{ code: number; stdout: string; stderr: string }>('python/run-command', {
        args: buildArgs('delivery'),
      });

      setDeliveryLogs([result.stdout, result.stderr].filter(Boolean).join('\n'));

      if (result.code !== 0) {
        setDeliveryStatus('error');
        showToast({ title: 'Delivery failed', description: result.stderr || 'Delivery command failed.', variant: 'error' });
        return;
      }

      setDeliveryStatus('success');
      handleComplete();
      showToast({
        title: 'Delivery complete',
        description: 'Delivery finished successfully.',
        actionLabel: 'View in Overview',
        onAction: handleComplete,
        variant: 'success',
      });
    } catch (error) {
      console.error('Failed to run delivery', error);
      setDeliveryStatus('error');
      setDeliveryLogs('');
      showToast({ title: 'Delivery error', description: 'Unable to start delivery.', variant: 'error' });
    }
  };

  const renderContentStep = (): JSX.Element => (
    <Card title="Select content">
      <div style={{ display: 'grid', gap: theme.spacing.md }}>
        <TextInput
          label="Delivery / playlist name"
          placeholder="Episode 102 - Client delivery"
          value={deliveryName}
          onChange={(event) => setDeliveryName(event.target.value)}
          required
        />
        <div style={{ display: 'grid', gap: '0.35rem' }}>
          <p style={{ margin: 0, fontWeight: theme.typography.fontWeightMedium }}>Type</p>
          <div
            style={{
              display: 'grid',
              gap: theme.spacing.sm,
              gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
            }}
          >
            {[
              { key: 'episode', label: 'Episode / Sequence', description: 'Deliver an entire episode or sequence block.' },
              { key: 'shots', label: 'Shot selection', description: 'Choose individual shots or ranges.' },
              { key: 'archviz', label: 'Arch-viz stills / turntables', description: 'Package stills or turntables.' },
            ].map((option) => {
              const isActive = deliveryType === option.key;
              return (
                <button
                  key={option.key}
                  onClick={() => setDeliveryType(option.key as DeliveryType)}
                  style={{
                    display: 'grid',
                    gap: '0.25rem',
                    padding: theme.spacing.sm,
                    borderRadius: theme.radii.md,
                    border: `1px solid ${isActive ? theme.colors.primary : theme.colors.border}`,
                    background: isActive ? theme.colors.surfaceAlt : theme.colors.surface,
                    textAlign: 'left',
                    cursor: 'pointer',
                  }}
                  type="button"
                >
                  <span style={{ fontWeight: theme.typography.fontWeightMedium }}>{option.label}</span>
                  <span style={{ color: theme.colors.textMuted, fontSize: theme.typography.fontSizeSm }}>
                    {option.description}
                  </span>
                </button>
              );
            })}
          </div>
        </div>
        <TextInput
          label="Shots / selection"
          placeholder="sh010, sh020 or seq10"
          value={shotSelection}
          onChange={(event) => setShotSelection(event.target.value)}
          description="List specific shots, sequences, or turntable labels."
        />
        {/* TODO: If project-info exposes a shot list via API/CLI, replace the free text selection with a dropdown or multi-select. */}
      </div>
    </Card>
  );

  const renderTargetsStep = (): JSX.Element => (
    <Card title="Choose delivery targets">
      <div style={{ display: 'grid', gap: theme.spacing.md }}>
        <label style={{ display: 'flex', gap: theme.spacing.sm, alignItems: 'flex-start' }}>
          <input
            type="checkbox"
            checked={includeShotgrid}
            onChange={(event) => setIncludeShotgrid(event.target.checked)}
            style={{ marginTop: '0.25rem' }}
          />
          <div style={{ display: 'grid', gap: '0.25rem' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: theme.spacing.xs }}>
              <strong>ShotGrid playlist</strong>
              {includeShotgrid ? <StatusBadge status="success">Enabled</StatusBadge> : null}
            </div>
            <TextInput
              label="Playlist name or ID"
              placeholder="client_preview_v1"
              value={shotgridPlaylist}
              onChange={(event) => setShotgridPlaylist(event.target.value)}
              disabled={!includeShotgrid}
              required={includeShotgrid}
            />
          </div>
        </label>

        <label style={{ display: 'flex', gap: theme.spacing.sm, alignItems: 'flex-start' }}>
          <input
            type="checkbox"
            checked={includeS3Mirror}
            onChange={(event) => setIncludeS3Mirror(event.target.checked)}
            style={{ marginTop: '0.25rem' }}
          />
          <div style={{ display: 'grid', gap: '0.25rem' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: theme.spacing.xs }}>
              <strong>S3 bucket mirror</strong>
              {includeS3Mirror ? <StatusBadge status="success">Enabled</StatusBadge> : null}
            </div>
            <TextInput
              label="S3 path (prefix)"
              placeholder="s3://bucket/client/episode102"
              value={s3Path}
              onChange={(event) => setS3Path(event.target.value)}
              disabled={!includeS3Mirror}
              required={includeS3Mirror}
            />
          </div>
        </label>

        <label style={{ display: 'flex', gap: theme.spacing.sm, alignItems: 'flex-start' }}>
          <input
            type="checkbox"
            checked={includeMediaShuttle}
            onChange={(event) => setIncludeMediaShuttle(event.target.checked)}
            style={{ marginTop: '0.25rem' }}
          />
          <div style={{ display: 'grid', gap: '0.25rem' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: theme.spacing.xs }}>
              <strong>MediaShuttle package</strong>
              {includeMediaShuttle ? <StatusBadge status="success">Enabled</StatusBadge> : null}
            </div>
            <TextInput
              label="Local staging folder"
              placeholder="/projects/onepiece/deliveries/client"
              value={stagingFolder}
              onChange={(event) => setStagingFolder(event.target.value)}
              disabled={!includeMediaShuttle}
              required={includeMediaShuttle}
            />
          </div>
        </label>
      </div>
    </Card>
  );

  const renderPreflightStep = (): JSX.Element => (
    <Card title="Preflight results">
      <div style={{ display: 'grid', gap: theme.spacing.md }}>
        {preflightStatus === 'idle' ? <p className="op-muted">Run the preflight to validate this delivery.</p> : null}
        {preflightStatus === 'running' ? <p className="op-muted">Running preflight…</p> : null}

        {preflightStatus === 'success' ? (
          <div style={{ display: 'grid', gap: theme.spacing.sm }}>
            {preflightResult.readyItems.length ? (
              <div>
                <h4 style={{ margin: '0 0 0.25rem' }}>Ready</h4>
                <ul style={{ margin: 0, paddingLeft: '1.2rem' }}>
                  {preflightResult.readyItems.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              </div>
            ) : null}
            {preflightResult.missingItems.length ? (
              <div>
                <h4 style={{ margin: '0 0 0.25rem' }}>Missing or mismatched</h4>
                <ul style={{ margin: 0, paddingLeft: '1.2rem', color: theme.colors.danger }}>
                  {preflightResult.missingItems.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              </div>
            ) : null}
            {preflightResult.warnings.length ? (
              <div>
                <h4 style={{ margin: '0 0 0.25rem' }}>Warnings</h4>
                <ul style={{ margin: 0, paddingLeft: '1.2rem', color: theme.colors.warning }}>
                  {preflightResult.warnings.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              </div>
            ) : null}
            {!preflightResult.readyItems.length && !preflightResult.missingItems.length && !preflightResult.warnings.length ? (
              <p className="op-muted">No issues reported in preflight.</p>
            ) : null}
          </div>
        ) : null}

        {preflightStatus === 'error' ? (
          <div>
            <p className="op-error">Preflight failed. Please review the logs below.</p>
            {preflightResult.error ? <pre className="op-log-output">{preflightResult.error}</pre> : null}
          </div>
        ) : null}

        {preflightResult.rawOutput ? (
          <div>
            <h4 style={{ margin: '0 0 0.25rem' }}>Raw output</h4>
            <pre className="op-log-output">{preflightResult.rawOutput}</pre>
          </div>
        ) : null}
      </div>
    </Card>
  );

  const renderDeliveryStep = (): JSX.Element => (
    <Card title="Delivery progress">
      <div style={{ display: 'grid', gap: theme.spacing.md }}>
        {deliveryStatus === 'idle' ? <p className="op-muted">Start delivery to see live logs and progress.</p> : null}
        {deliveryStatus === 'running' ? <p className="op-muted">Running delivery…</p> : null}
        {deliveryStatus === 'success' ? <StatusBadge status="success">Delivery completed</StatusBadge> : null}
        {deliveryStatus === 'error' ? <StatusBadge status="error">Delivery failed</StatusBadge> : null}

        {deliveryLogs ? <pre className="op-log-output">{deliveryLogs}</pre> : null}
      </div>
    </Card>
  );

  const renderStep = (): JSX.Element => {
    switch (currentStep) {
      case 0:
        return renderContentStep();
      case 1:
        return renderTargetsStep();
      case 2:
        return renderPreflightStep();
      case 3:
        return renderDeliveryStep();
      default:
        return renderContentStep();
    }
  };

  const handlePrimary = (): void => {
    if (currentStep === 0) {
      setCurrentStep(1);
      return;
    }

    if (currentStep === 1) {
      void runPreflight();
      return;
    }

    if (currentStep === 2) {
      if (preflightStatus !== 'success') {
        void runPreflight();
        return;
      }

      setCurrentStep(3);
      void runDelivery();
      return;
    }

    if (currentStep === 3) {
      handleResetAndClose();
    }
  };

  const handleBack = (): void => {
    if (currentStep === 0) {
      return;
    }

    if (currentStep === 3) {
      setDeliveryStatus('idle');
      setDeliveryLogs('');
      setCurrentStep(2);
      return;
    }

    setCurrentStep((prev) => (prev > 0 ? ((prev - 1) as WizardStep) : prev));
  };

  const primaryLabel = useMemo(() => {
    if (currentStep === 0) return 'Next';
    if (currentStep === 1) return preflightStatus === 'running' ? 'Running…' : 'Run preflight';
    if (currentStep === 2) {
      if (preflightStatus === 'running') return 'Running…';
      if (preflightStatus === 'success') return deliveryStatus === 'running' ? 'Starting…' : 'Start delivery';
      return 'Run preflight';
    }
    return deliveryStatus === 'success' ? 'Close' : deliveryStatus === 'running' ? 'Running…' : 'Close';
  }, [currentStep, deliveryStatus, preflightStatus]);

  const primaryDisabled = useMemo(() => {
    if (currentStep === 0) return !canProceedFromContent;
    if (currentStep === 1) return !canProceedFromTargets || preflightStatus === 'running';
    if (currentStep === 2) return preflightStatus === 'running' || deliveryStatus === 'running';
    if (currentStep === 3) return deliveryStatus === 'running';
    return false;
  }, [canProceedFromContent, canProceedFromTargets, currentStep, deliveryStatus, preflightStatus]);

  return (
    <Modal
      isOpen
      onClose={handleResetAndClose}
      title="Client Delivery"
      description="Guide for building a client-facing delivery package for OnePiece Studio Desktop."
      primaryAction={{ label: primaryLabel, onClick: handlePrimary, disabled: primaryDisabled }}
      secondaryAction={{ label: 'Back', onClick: handleBack, disabled: currentStep === 0 }}
    >
      <div style={{ display: 'grid', gap: theme.spacing.lg }}>
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: theme.spacing.sm,
            flexWrap: 'wrap',
          }}
        >
          <StepIndicator currentStep={currentStep} />
          {onOpenShotgridOps ? (
            <Button variant="ghost" size="sm" onClick={() => onOpenShotgridOps()}>
              Open advanced ShotGrid operations
            </Button>
          ) : null}
        </div>
        {!hasProject ? <p className="op-error">No project selected. Set a project to continue.</p> : null}
        <WizardStepContainer stepKey={currentStep}>{renderStep()}</WizardStepContainer>
      </div>
    </Modal>
  );
}

export default DeliveryWizard;
