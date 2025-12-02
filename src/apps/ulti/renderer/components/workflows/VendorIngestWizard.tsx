import React, { useEffect, useMemo, useRef, useState } from 'react';
import { useTheme } from '../../styles/ThemeContext';
import { useHelpContext } from '../HelpContext';
import { Button, Card, Modal, SectionHeader, StatusBadge, TextInput, useToast } from '../ui';

type WizardStep = 1 | 2 | 3 | 4;

type VendorIngestWizardProps = {
  isOpen: boolean;
  project?: { name: string; path: string } | null;
  onClose: () => void;
  onCompleted?: () => void;
  onViewTasks?: () => void;
};

type TaskStatus = 'pending' | 'running' | 'succeeded' | 'failed';

type Task = {
  id: string;
  label: string;
  status: TaskStatus;
  createdAt: string;
  startedAt?: string;
  finishedAt?: string;
  exitCode?: number;
};

type PreflightState = {
  status: 'idle' | 'running' | 'succeeded' | 'failed';
  files?: number;
  folders?: number;
  totalSize?: string;
  warnings: string[];
  blockingIssues: string[];
  rawOutput?: string;
  stderr?: string;
  error?: string;
};

type IngestState = {
  taskId?: string;
  status: TaskStatus | 'idle';
  logs: string[];
  error?: string;
  startedAt?: string;
};

declare global {
  interface Window {
    electron: {
      invoke: <T = unknown>(channel: string, payload?: unknown) => Promise<T>;
      on?: (channel: string, listener: (_event: unknown, payload: Task[] | Task) => void) => () => void;
    };
  }
}

const stepLabels = ['Source', 'Preflight', 'Review', 'Ingest'];

const defaultPreflightState: PreflightState = {
  status: 'idle',
  warnings: [],
  blockingIssues: [],
};

const defaultIngestState: IngestState = {
  status: 'idle',
  logs: [],
};

const formatCount = (value?: number): string => {
  if (typeof value === 'number') {
    return value.toLocaleString();
  }

  return 'N/A';
};

const formatDateTime = (value?: string): string => {
  if (!value) {
    return '—';
  }

  return new Date(value).toLocaleString();
};

const parsePreflightOutput = (stdout: string, stderr: string): Omit<PreflightState, 'status'> => {
  const warnings: string[] = [];
  const blockingIssues: string[] = [];
  let files: number | undefined;
  let folders: number | undefined;
  let totalSize: string | undefined;

  try {
    const parsed = JSON.parse(stdout);
    files = parsed.files ?? parsed.fileCount;
    folders = parsed.folders ?? parsed.folderCount;
    totalSize = parsed.totalSize ?? parsed.size;
    if (Array.isArray(parsed.warnings)) {
      warnings.push(...parsed.warnings.map((item: unknown) => String(item)));
    }
    if (Array.isArray(parsed.blockingIssues)) {
      blockingIssues.push(...parsed.blockingIssues.map((item: unknown) => String(item)));
    }
  } catch (error) {
    const fileMatch = stdout.match(/(\d+)\s+files?/i);
    const folderMatch = stdout.match(/(\d+)\s+folders?/i);
    const sizeMatch = stdout.match(/(\d+(?:\.\d+)?)\s*(gb|tb|mb)/i);

    files = fileMatch ? Number(fileMatch[1]) : undefined;
    folders = folderMatch ? Number(folderMatch[1]) : undefined;
    totalSize = sizeMatch ? `${sizeMatch[1]} ${sizeMatch[2].toUpperCase()}` : undefined;

    stdout
      .split('\n')
      .map((line) => line.trim())
      .filter(Boolean)
      .forEach((line) => {
        const lower = line.toLowerCase();
        if (lower.startsWith('warning') || lower.includes('warning:')) {
          warnings.push(line.replace(/^(warning:?)\s*/i, ''));
        } else if (lower.startsWith('error') || lower.includes('failed')) {
          blockingIssues.push(line.replace(/^(error:?)\s*/i, ''));
        }
      });

    if (!blockingIssues.length && stderr.trim()) {
      blockingIssues.push(...stderr.trim().split('\n').map((line) => line.trim()));
    }
  }

  return { files, folders, totalSize, warnings, blockingIssues, rawOutput: stdout, stderr };
};

function StepIndicator({ currentStep }: { currentStep: WizardStep }): JSX.Element {
  const theme = useTheme();

  return (
    <div style={{ display: 'grid', gap: theme.spacing.xs }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span style={{ color: theme.colors.textMuted, fontSize: theme.typography.fontSizeSm }}>
          Step {currentStep} of {stepLabels.length}
        </span>
      </div>
      <ol
        aria-label="Wizard steps"
        style={{
          listStyle: 'none',
          padding: 0,
          margin: 0,
          display: 'grid',
          gridTemplateColumns: `repeat(${stepLabels.length}, minmax(0, 1fr))`,
          gap: theme.spacing.sm,
        }}
      >
        {stepLabels.map((label, index) => {
          const stepNumber = (index + 1) as WizardStep;
          const isActive = currentStep === stepNumber;
          const isComplete = currentStep > stepNumber;
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

function NotesField({
  label,
  value,
  placeholder,
  onChange,
  helpText,
}: {
  label: string;
  value: string;
  placeholder?: string;
  helpText?: string;
  onChange: (value: string) => void;
}): JSX.Element {
  const theme = useTheme();

  return (
    <label style={{ display: 'grid', gap: '0.35rem', width: '100%' }}>
      <span
        style={{
          fontWeight: theme.typography.fontWeightMedium,
          color: theme.colors.text,
          fontSize: theme.typography.fontSizeSm,
        }}
      >
        {label}
      </span>
      <textarea
        rows={4}
        value={value}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
        style={{
          background: theme.colors.surfaceAlt,
          color: theme.colors.text,
          border: `1px solid ${theme.colors.border}`,
          borderRadius: theme.radii.md,
          padding: `${theme.spacing.sm} ${theme.spacing.md}`,
          fontSize: theme.typography.fontSizeBase,
          fontFamily: theme.typography.fontFamily,
          resize: 'vertical',
          minHeight: '120px',
        }}
      />
      {helpText ? <span style={{ color: theme.colors.textMuted, fontSize: theme.typography.fontSizeSm }}>{helpText}</span> : null}
    </label>
  );
}

function VendorIngestWizard({
  isOpen,
  project,
  onClose,
  onCompleted,
  onViewTasks,
}: VendorIngestWizardProps): JSX.Element | null {
  const theme = useTheme();
  const { showToast } = useToast();
  const [currentStep, setCurrentStep] = useState<WizardStep>(1);
  const [sourcePath, setSourcePath] = useState('');
  const [deliveryName, setDeliveryName] = useState('');
  const [notes, setNotes] = useState('');
  const [sourceError, setSourceError] = useState<string | null>(null);
  const [preflight, setPreflight] = useState<PreflightState>(defaultPreflightState);
  const [ingest, setIngest] = useState<IngestState>(defaultIngestState);
  const hasShownSuccessToast = useRef(false);
  const previousIngestStatus = useRef<IngestState['status']>('idle');

  useHelpContext(
    isOpen
      ? currentStep === 1
        ? 'wizard.vendorIngest.step1'
        : currentStep === 2
          ? 'wizard.vendorIngest.step2'
          : currentStep === 3
            ? 'wizard.vendorIngest.step3'
            : 'wizard.vendorIngest.step4'
      : null,
  );

  useEffect(() => {
    if (!isOpen) {
      return;
    }

    setCurrentStep(1);
    setSourceError(null);
    setPreflight(defaultPreflightState);
    setIngest(defaultIngestState);
    hasShownSuccessToast.current = false;
  }, [isOpen]);

  const handleBrowseSource = async (): Promise<void> => {
    try {
      // TODO: wire up a real folder picker IPC
      const result = await window.electron.invoke<string | undefined>('dialog/open-folder');
      if (result) {
        setSourcePath(result);
        setSourceError(null);
      }
    } catch (error) {
      console.warn('Folder picker not implemented yet', error);
    }
  };

  const runPreflight = async (): Promise<void> => {
    if (!project?.path) {
      return;
    }

    setPreflight({ ...defaultPreflightState, status: 'running' });
    setCurrentStep(2);

    try {
      const result = await window.electron.invoke<{ code: number; stdout: string; stderr: string }>(
        'python/run-command',
        {
          args: ['-m', 'onepiece', 'ingest-preflight', '--source', sourcePath, '--project-root', project.path],
        },
      );

      const parsed = parsePreflightOutput(result.stdout, result.stderr);
      const status = result.code === 0 ? 'succeeded' : 'failed';

      setPreflight({
        status,
        ...parsed,
        error: status === 'failed' ? `Preflight exited with code ${result.code}` : undefined,
      });
    } catch (error) {
      setPreflight({
        ...defaultPreflightState,
        status: 'failed',
        error: error instanceof Error ? error.message : 'Preflight failed.',
      });
    }
  };

  const refreshTask = async (taskId: string): Promise<void> => {
    try {
      const tasks = await window.electron.invoke<Task[]>('tasks/list');
      const match = tasks.find((task) => task.id === taskId);

      if (match) {
        setIngest((prev) => ({
          ...prev,
          status: match.status,
          taskId,
          startedAt: prev.startedAt ?? match.startedAt,
        }));
      }
    } catch (error) {
      console.error('Failed to refresh task state', error);
    }
  };

  useEffect(() => {
    if (!ingest.taskId) {
      return undefined;
    }

    const unsubscribe = window.electron.on?.('tasks/updated', (_event, payload: Task[] | Task) => {
      const tasks = Array.isArray(payload) ? payload : [payload];
      const match = tasks.find((task) => task.id === ingest.taskId);
      if (match) {
        setIngest((prev) => ({
          ...prev,
          status: match.status,
          taskId: ingest.taskId,
          startedAt: prev.startedAt ?? match.startedAt,
        }));
      }
    });

    const interval = window.setInterval(() => {
      void refreshTask(ingest.taskId as string);
    }, 4000);

    return () => {
      if (unsubscribe) {
        unsubscribe();
      }
      window.clearInterval(interval);
    };
  }, [ingest.taskId]);

  useEffect(() => {
    if (ingest.status === 'succeeded' && !hasShownSuccessToast.current) {
      hasShownSuccessToast.current = true;

      showToast({
        kind: 'success',
        message: `Vendor ingest complete for "${deliveryName || sourcePath}"`,
        actionLabel: 'Open overview',
        onAction: () => {
          onCompleted?.();
          onClose();
        },
      });
    }
  }, [deliveryName, ingest.status, onClose, onCompleted, showToast, sourcePath]);

  useEffect(() => {
    if (ingest.status === previousIngestStatus.current || ingest.status === 'idle') {
      return;
    }

    previousIngestStatus.current = ingest.status;
    setIngest((prev) => ({
      ...prev,
      logs: [
        ...prev.logs,
        ingest.status === 'succeeded'
          ? 'Ingest completed successfully.'
          : ingest.status === 'failed'
            ? 'Ingest failed. View the Tasks tab for full details.'
            : 'Ingest running…',
      ],
    }));
  }, [ingest.status]);

  const startIngest = async (): Promise<void> => {
    if (!project?.path) {
      return;
    }

    const startedAt = new Date().toISOString();
    setCurrentStep(4);
    setIngest({ status: 'running', logs: ['Starting ingest…'], startedAt });

    try {
      const label = `Vendor ingest – ${project?.name ?? 'Unknown project'}`;
      const taskId = await window.electron.invoke<string>('tasks/create', {
        label,
        args: ['-m', 'onepiece', 'ingest', '--source', sourcePath, '--project-root', project.path],
      });

      setIngest({
        status: 'running',
        taskId,
        logs: [`Task created (id: ${taskId}).`, 'Monitoring progress…'],
        startedAt,
      });

      await refreshTask(taskId);
    } catch (error) {
      setIngest({
        status: 'failed',
        logs: [],
        error: error instanceof Error ? error.message : 'Failed to start ingest.',
      });
    }
  };

  const canProceedFromSource = Boolean(project && sourcePath.trim());
  const preflightHasWarnings = preflight.warnings.length > 0;
  const preflightHasBlockingIssues = preflight.blockingIssues.length > 0;

  const handleSourceNext = (): void => {
    if (!project) {
      return;
    }

    if (!sourcePath.trim()) {
      setSourceError('Please select a source folder.');
      return;
    }

    void runPreflight();
  };

  const preflightSummary = useMemo(() => {
    if (preflight.status === 'running') {
      return 'Scanning files, checking naming and expected structure…';
    }

    if (preflight.status === 'failed') {
      return preflight.error ?? 'Preflight failed';
    }

    const files = formatCount(preflight.files);
    const folders = formatCount(preflight.folders);
    return `${files} files across ${folders} folders`;
  }, [preflight.error, preflight.files, preflight.folders, preflight.status]);

  const ingestStatusLabel = useMemo(() => {
    switch (ingest.status) {
      case 'running':
        return 'Running';
      case 'succeeded':
        return 'Succeeded';
      case 'failed':
        return 'Failed';
      case 'pending':
        return 'Pending';
      default:
        return 'Idle';
    }
  }, [ingest.status]);

  const renderSourceStep = (): JSX.Element => (
    <div style={{ display: 'grid', gap: theme.spacing.md }}>
      <SectionHeader
        title="Choose source folder"
        subtitle="Pick the folder where your vendor has delivered plates, textures, or assets."
      />
      <Card>
        <div style={{ display: 'grid', gap: theme.spacing.md }}>
          <div style={{ display: 'grid', gap: theme.spacing.xs }}>
            <div style={{ display: 'grid', gap: theme.spacing.sm }}>
              <div style={{ display: 'flex', gap: theme.spacing.sm, alignItems: 'flex-end' }}>
                <div style={{ flex: 1 }}>
                  <TextInput
                    label="Source folder"
                    placeholder="\\\\server\\show\\vendor\\delivery_2025_12_01"
                    value={sourcePath}
                    onChange={(event) => setSourcePath(event.target.value)}
                    onBlur={() => {
                      if (!sourcePath.trim()) {
                        setSourceError('Please select a source folder.');
                      }
                    }}
                    errorText={sourceError ?? undefined}
                    helpText="This is the top-level folder containing the files you want to ingest. Subfolders will be scanned automatically."
                    required
                  />
                </div>
                <Button variant="secondary" onClick={() => void handleBrowseSource()}>
                  Browse…
                </Button>
              </div>
            </div>
          </div>

          {project ? (
            <Card title="Project">
              <div style={{ display: 'grid', gap: '0.25rem' }}>
                <strong>{project.name}</strong>
                <p style={{ margin: 0, color: theme.colors.textMuted }}>This ingest will be attached to this project.</p>
              </div>
            </Card>
          ) : (
            <Card>
              <div style={{ display: 'grid', gap: theme.spacing.xs }}>
                <p style={{ margin: 0, fontWeight: theme.typography.fontWeightBold }}>No project selected</p>
                <p style={{ margin: 0, color: theme.colors.textMuted }}>
                  Select or create a project before running a vendor ingest. This helps OnePiece keep your deliveries
                  organised.
                </p>
                <div>
                  <Button variant="secondary" onClick={onClose}>
                    Go to project selection
                  </Button>
                </div>
              </div>
            </Card>
          )}

          <div style={{ display: 'grid', gap: theme.spacing.sm }}>
            <TextInput
              label="Delivery name (optional)"
              placeholder="Vendor_XY_Plates_v002"
              value={deliveryName}
              onChange={(event) => setDeliveryName(event.target.value)}
              helpText="Used for tracking this delivery in logs and dashboards."
            />
            <NotesField
              label="Notes (optional)"
              value={notes}
              placeholder="Hero plates for seq 010, colour corrected, includes mattes."
              helpText="Add any context you want to remember when reviewing this ingest later."
              onChange={setNotes}
            />
          </div>
        </div>
      </Card>
      <p style={{ margin: 0, color: theme.colors.textMuted }}>
        Ingest will continue even if you close this window.
      </p>
    </div>
  );

  const renderPreflightStep = (): JSX.Element => (
    <div style={{ display: 'grid', gap: theme.spacing.md }}>
      <SectionHeader title="Preflight checks" subtitle="Analysing your source folder and project structure." />
      <Card>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: theme.spacing.md }}>
          <div style={{ display: 'grid', gap: '0.35rem' }}>
            <div style={{ display: 'flex', gap: theme.spacing.sm, alignItems: 'center' }}>
              <StatusBadge
                status={
                  preflight.status === 'succeeded'
                    ? preflightHasWarnings
                      ? 'Warnings found'
                      : 'All checks passed'
                    : preflight.status === 'failed'
                      ? 'Preflight failed'
                      : 'Running'
                }
              >
                {preflight.status === 'running'
                  ? 'Running checks'
                  : preflight.status === 'failed'
                    ? 'Preflight failed'
                    : preflightHasWarnings
                      ? 'Warnings found'
                      : 'All checks passed'}
              </StatusBadge>
              <span style={{ color: theme.colors.textMuted }}>{preflightSummary}</span>
            </div>
            {preflight.status === 'running' ? (
              <div style={{ color: theme.colors.textMuted, display: 'grid', gap: '0.25rem' }}>
                <span>Scanning files, checking naming and expected structure…</span>
                <ul style={{ margin: 0, paddingLeft: '1.1rem', color: theme.colors.textMuted }}>
                  <li>Checking file count and types…</li>
                  <li>Checking naming conventions…</li>
                  <li>Checking for missing or duplicate frames…</li>
                </ul>
              </div>
            ) : null}
          </div>
          {preflight.status !== 'running' ? (
            <Button variant="secondary" onClick={() => void runPreflight()}>
              Run preflight again
            </Button>
          ) : null}
        </div>
      </Card>

      {preflight.status === 'succeeded' ? (
        <Card title="Summary">
          <dl className="op-definition-list">
            <div>
              <dt>Files scanned</dt>
              <dd>{formatCount(preflight.files)}</dd>
            </div>
            <div>
              <dt>Folders</dt>
              <dd>{formatCount(preflight.folders)}</dd>
            </div>
            <div>
              <dt>Total size</dt>
              <dd>{preflight.totalSize ?? 'N/A'}</dd>
            </div>
          </dl>
          <p style={{ margin: 0, color: theme.colors.textMuted }}>
            {preflightHasWarnings
              ? 'You can still run the ingest, but we recommend reviewing these warnings and fixing them where possible.'
              : 'We didn’t find any blocking issues. Minor warnings may still be present — review them below.'}
          </p>
        </Card>
      ) : null}

      {preflight.status === 'failed' ? (
        <Card title="Blocking issues">
          {preflight.blockingIssues.length ? (
            <ul style={{ margin: 0, paddingLeft: '1.1rem', color: theme.colors.danger }}>
              {preflight.blockingIssues.map((warning, index) => (
                <li key={`${warning}-${index}`}>{warning}</li>
              ))}
            </ul>
          ) : (
            <p style={{ margin: 0, color: theme.colors.danger }}>
              We found one or more issues that would cause this ingest to fail.
            </p>
          )}
          {preflight.stderr ? (
            <pre
              style={{
                marginTop: theme.spacing.sm,
                padding: theme.spacing.sm,
                background: theme.colors.surfaceAlt,
                borderRadius: theme.radii.sm,
                border: `1px solid ${theme.colors.border}`,
                overflow: 'auto',
                maxHeight: '240px',
              }}
            >
              {preflight.stderr}
            </pre>
          ) : null}
        </Card>
      ) : null}

      {preflightHasWarnings ? (
        <Card title="Warnings">
          <ul style={{ margin: 0, paddingLeft: '1.1rem', display: 'grid', gap: '0.35rem' }}>
            {preflight.warnings.map((warning, index) => (
              <li key={`${warning}-${index}`}>{warning}</li>
            ))}
          </ul>
        </Card>
      ) : (
        preflight.status === 'succeeded' && (
          <Card>
            <p style={{ margin: 0 }}>No warnings found.</p>
          </Card>
        )
      )}
    </div>
  );

  const renderReviewStep = (): JSX.Element => (
    <div style={{ display: 'grid', gap: theme.spacing.md }}>
      <SectionHeader title="Review & confirm" subtitle="Check the summary below, then start the ingest." />
      <Card title="Summary">
        <dl className="op-definition-list">
          <div>
            <dt>Project</dt>
            <dd>{project?.name ?? 'Not set'}</dd>
          </div>
          <div>
            <dt>Project root</dt>
            <dd>{project?.path ?? 'Not set'}</dd>
          </div>
          <div>
            <dt>Source folder</dt>
            <dd>{sourcePath}</dd>
          </div>
          <div>
            <dt>Delivery name</dt>
            <dd>{deliveryName || 'Not set'}</dd>
          </div>
          <div>
            <dt>Notes</dt>
            <dd>{notes || 'None'}</dd>
          </div>
          <div>
            <dt>Files</dt>
            <dd>{preflight.files ? `${formatCount(preflight.files)}${preflight.totalSize ? ` • ${preflight.totalSize}` : ''}` : 'N/A'}</dd>
          </div>
          <div>
            <dt>Warnings</dt>
            <dd>
              {preflight.warnings.length ? (
                <details>
                  <summary>{preflight.warnings.length} warning(s)</summary>
                  <ul style={{ margin: `${theme.spacing.xs} 0 0`, paddingLeft: '1.1rem' }}>
                    {preflight.warnings.map((warning, index) => (
                      <li key={`${warning}-${index}`}>{warning}</li>
                    ))}
                  </ul>
                </details>
              ) : (
                'None'
              )}
            </dd>
          </div>
        </dl>
        <p style={{ margin: 0, color: theme.colors.textMuted }}>
          {preflight.warnings.length
            ? 'You can still proceed, but these warnings may cause issues down the line. Consider addressing them before running major work on this delivery.'
            : 'Everything looks ready. You can start the ingest when you’re ready.'}
        </p>
      </Card>
    </div>
  );

  const renderIngestStep = (): JSX.Element => (
    <div style={{ display: 'grid', gap: theme.spacing.md }}>
      <SectionHeader title="Ingest in progress" subtitle="You can keep working while we ingest your delivery." />
      <Card>
        <div style={{ display: 'grid', gap: theme.spacing.sm }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: theme.spacing.md }}>
            <div style={{ display: 'grid', gap: '0.25rem' }}>
              <span style={{ color: theme.colors.textMuted }}>Task:</span>
              <strong>{`Vendor ingest – ${project?.name ?? 'Unknown project'}`}</strong>
              <span style={{ color: theme.colors.textMuted }}>
                Started: {formatDateTime(ingest.startedAt)}
              </span>
            </div>
            <StatusBadge status={ingestStatusLabel}>{ingestStatusLabel}</StatusBadge>
          </div>

          <div style={{ background: theme.colors.surfaceAlt, borderRadius: theme.radii.sm, padding: theme.spacing.sm }}>
            <p style={{ margin: 0, color: theme.colors.textMuted }}>Recent activity</p>
            <div style={{ display: 'grid', gap: '0.25rem', marginTop: theme.spacing.xs }}>
              {ingest.logs.length ? (
                ingest.logs.slice(-6).map((log, index) => (
                  <span key={`${log}-${index}`} style={{ color: theme.colors.text }}>
                    {log}
                  </span>
                ))
              ) : (
                <span style={{ color: theme.colors.textMuted }}>
                  {ingest.status === 'failed'
                    ? 'The ingest stopped with an error. Check the details below.'
                    : 'Waiting for task updates…'}
                </span>
              )}
            </div>
          </div>

          {ingest.status === 'failed' && ingest.error ? (
            <Card>
              <p style={{ margin: 0, color: theme.colors.danger }}>
                The ingest stopped with an error. Check the details below and fix any issues before trying again.
              </p>
              <pre
                style={{
                  marginTop: theme.spacing.sm,
                  padding: theme.spacing.sm,
                  background: theme.colors.surfaceAlt,
                  borderRadius: theme.radii.sm,
                  border: `1px solid ${theme.colors.border}`,
                  overflow: 'auto',
                  maxHeight: '240px',
                }}
              >
                {ingest.error}
              </pre>
            </Card>
          ) : null}

          <p style={{ margin: 0, color: theme.colors.textMuted }}>
            You can close this window at any time. The ingest will continue in the background. Check the Tasks tab for
            full progress.
          </p>
        </div>
      </Card>
    </div>
  );

  const primaryAction = useMemo(() => {
    if (!isOpen) {
      return { label: 'Close', onClick: onClose };
    }

    switch (currentStep) {
      case 1:
        return {
          label: 'Next',
          onClick: handleSourceNext,
          disabled: !canProceedFromSource,
        };
      case 2:
        return {
          label: preflight.status === 'running' ? 'Running…' : 'Continue',
          onClick: () => setCurrentStep(3),
          disabled: preflight.status !== 'succeeded',
        };
      case 3:
        return {
          label: 'Run ingest',
          onClick: () => void startIngest(),
          disabled: ingest.status === 'running',
        };
      case 4:
      default:
        return {
          label: ingest.status === 'succeeded' ? 'Back to overview' : 'Close',
          onClick: () => {
            if (ingest.status === 'succeeded') {
              onCompleted?.();
            }
            onClose();
          },
        };
    }
  }, [canProceedFromSource, currentStep, ingest.status, isOpen, onClose, onCompleted, preflight.status]);

  const secondaryAction = useMemo(() => {
    if (!isOpen) {
      return undefined;
    }

    switch (currentStep) {
      case 1:
        return { label: 'Cancel', onClick: onClose, variant: 'secondary' as const };
      case 2:
      case 3:
        return {
          label: 'Back',
          onClick: () => setCurrentStep((prev) => (prev > 1 ? ((prev - 1) as WizardStep) : prev)),
          variant: 'secondary' as const,
          disabled: preflight.status === 'running' || ingest.status === 'running',
        };
      case 4:
        return onViewTasks
          ? {
              label: 'View tasks',
              onClick: onViewTasks,
              variant: 'secondary' as const,
            }
          : undefined;
      default:
        return undefined;
    }
  }, [currentStep, ingest.status, isOpen, onClose, onViewTasks, preflight.status]);

  const renderStepContent = (): JSX.Element => {
    switch (currentStep) {
      case 1:
        return renderSourceStep();
      case 2:
        return renderPreflightStep();
      case 3:
        return renderReviewStep();
      case 4:
      default:
        return renderIngestStep();
    }
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title="Vendor ingest"
      description="Bring external deliveries into your project in a controlled, repeatable way."
      primaryAction={primaryAction}
      secondaryAction={secondaryAction}
    >
      <div style={{ display: 'grid', gap: theme.spacing.lg }}>
        <div style={{ display: 'grid', gap: '0.25rem' }}>
          <h3 style={{ margin: 0 }}>Vendor ingest</h3>
          <p style={{ margin: 0, color: theme.colors.textMuted }}>
            Bring external deliveries into your project in a controlled, repeatable way.
          </p>
        </div>
        <StepIndicator currentStep={currentStep} />
        {renderStepContent()}
        {currentStep === 4 && ingest.status === 'running' ? (
          <p style={{ margin: 0, color: theme.colors.warning }}>
            Ingest will continue in the background even if you close this window.
          </p>
        ) : null}
      </div>
    </Modal>
  );
}

export default VendorIngestWizard;
