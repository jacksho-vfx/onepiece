import React, { useEffect, useMemo, useState } from 'react';
import { Button, Modal, TextInput, useToast } from '../ui';
import { useTheme } from '../../styles/ThemeContext';

interface SubmitRenderModalProps {
  isOpen: boolean;
  onClose: () => void;
  project?: { name: string; path: string };
  defaultProfile?: string;
  onViewTasks?: () => void;
}

const DEFAULT_PRIORITY = 80;

function SubmitRenderModal({ isOpen, onClose, project, defaultProfile, onViewTasks }: SubmitRenderModalProps): JSX.Element | null {
  const theme = useTheme();
  const { showToast } = useToast();

  // TODO: Surface additional render submit flags (adapter, chunk sizing, etc.) as the CLI options solidify.

  const [profile, setProfile] = useState(defaultProfile ?? '');
  const [scenePath, setScenePath] = useState('');
  const [frameRange, setFrameRange] = useState('');
  const [outputPath, setOutputPath] = useState('');
  const [user, setUser] = useState('');
  const [priority, setPriority] = useState<string>(String(DEFAULT_PRIORITY));
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    if (!isOpen) {
      return;
    }

    setError(null);

    setProfile((current) => current || defaultProfile || '');
    setOutputPath((current) => current || project?.path || '');
    setPriority((current) => (current ? current : String(DEFAULT_PRIORITY)));
  }, [defaultProfile, isOpen, project?.path]);

  useEffect(() => {
    if (!isOpen || user) {
      return;
    }

    let isActive = true;
    window.electron
      .invoke<string | null>('system/get-username')
      .then((username) => {
        if (isActive && username) {
          setUser(username);
        }
      })
      .catch(() => {
        // Best effort only; silently ignore failures.
      });

    return () => {
      isActive = false;
    };
  }, [isOpen, user]);

  const buildPickerError = (reason: unknown, target: 'file' | 'folder') => {
    const fallback = target === 'file' ? 'Unable to open file picker.' : 'Unable to open folder picker.';
    const rawMessage = reason instanceof Error ? reason.message : typeof reason === 'string' ? reason : null;
    const normalized = rawMessage?.toLowerCase();

    if (normalized?.includes('cancel')) {
      const cancelled = `${target === 'file' ? 'File' : 'Folder'} picker was cancelled.`;
      return { log: cancelled, user: cancelled };
    }

    const detailed = rawMessage ? `${fallback} (${rawMessage})` : fallback;
    const log = rawMessage ? `${fallback} ${rawMessage}` : fallback;

    return { log, user: detailed };
  };

  const handleBrowseScene = async (): Promise<void> => {
    try {
      const selected = await window.electron.invoke<string | null>('dialog/open-file', {
        title: 'Select scene file',
      });
      if (selected) {
        setScenePath(selected);
      }
    } catch (err) {
      const { log, user } = buildPickerError(err, 'file');
      console.error(log, err);
      setError(user);
    }
  };

  const handleBrowseOutput = async (): Promise<void> => {
    try {
      const selected = await window.electron.invoke<string | null>('dialog/open-folder', {
        title: 'Select output directory',
        defaultPath: project?.path,
      });
      if (selected) {
        setOutputPath(selected);
      }
    } catch (err) {
      const { log, user } = buildPickerError(err, 'folder');
      console.error(log, err);
      setError(user);
    }
  };

  const hasRequiredFields = useMemo(() => {
    return Boolean(scenePath.trim() && outputPath.trim() && frameRange.trim());
  }, [frameRange, outputPath, scenePath]);

  const handleSubmit = async (): Promise<void> => {
    if (!hasRequiredFields) {
      setError('Scene path, frame range, and output directory are required.');
      return;
    }

    const trimmedPriority = priority.trim();
    const parsedPriority = trimmedPriority ? Number(trimmedPriority) : undefined;

    if (trimmedPriority && Number.isNaN(parsedPriority)) {
      setError('Priority must be a number.');
      return;
    }

    setIsSubmitting(true);
    setError(null);

    try {
      const taskId = await window.electron.invoke<string>('onepiece/render-submit', {
        profile: profile.trim() || undefined,
        scene: scenePath.trim(),
        frames: frameRange.trim(),
        output: outputPath.trim(),
        user: user.trim() || undefined,
        priority: parsedPriority,
      });

      showToast({
        kind: 'success',
        message: taskId ? `Render submitted (task #${taskId})` : 'Render submitted',
        actionLabel: onViewTasks ? 'View tasks' : undefined,
        onAction: onViewTasks,
      });

      onClose();
    } catch (err) {
      console.error('Failed to submit render', err);
      setError((err as Error)?.message ?? 'Unable to submit render.');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Modal
      title="Submit render"
      description="Wraps `onepiece render submit` with your defaults."
      isOpen={isOpen}
      onClose={onClose}
      primaryAction={{
        label: 'Submit render',
        onClick: () => void handleSubmit(),
        isLoading: isSubmitting,
        disabled: isSubmitting || !hasRequiredFields,
      }}
      secondaryAction={{
        label: 'Cancel',
        onClick: onClose,
        variant: 'secondary',
        disabled: isSubmitting,
      }}
    >
      <div style={{ display: 'grid', gap: theme.spacing.md }}>
        <div style={{ display: 'grid', gap: theme.spacing.sm }}>
          <TextInput
            label="Render profile"
            placeholder="studio_farm"
            value={profile}
            onChange={(event) => setProfile(event.target.value)}
            helpText="Optional. Uses your default render profile when blank."
          />

          <div style={{ display: 'grid', gap: theme.spacing.xs }}>
            <div style={{ display: 'flex', gap: theme.spacing.sm }}>
              <TextInput
                label="Scene file"
                placeholder="/path/to/scene.ma"
                value={scenePath}
                onChange={(event) => setScenePath(event.target.value)}
                style={{ flex: 1 }}
              />
              <Button variant="secondary" onClick={() => void handleBrowseScene()}>
                Browse…
              </Button>
            </div>
          </div>

          <div style={{ display: 'grid', gap: theme.spacing.xs }}>
            <div style={{ display: 'flex', gap: theme.spacing.sm }}>
              <TextInput
                label="Output directory"
                placeholder="/path/to/output"
                value={outputPath}
                onChange={(event) => setOutputPath(event.target.value)}
                style={{ flex: 1 }}
              />
              <Button variant="secondary" onClick={() => void handleBrowseOutput()}>
                Browse…
              </Button>
            </div>
          </div>

          <TextInput
            label="Frame range"
            placeholder="1001-1012"
            value={frameRange}
            onChange={(event) => setFrameRange(event.target.value)}
            helpText="Provide a frame range like 1001-1012."
          />

          <TextInput
            label="User"
            placeholder="janed"
            value={user}
            onChange={(event) => setUser(event.target.value)}
            helpText="Defaults to the current OS user."
          />

          <TextInput
            label="Priority"
            type="number"
            min="0"
            max="100"
            value={priority}
            onChange={(event) => setPriority(event.target.value)}
            helpText="Optional priority; defaults to 80."
          />
        </div>

        {error ? (
          <div
            style={{
              padding: `${theme.spacing.sm} ${theme.spacing.md}`,
              borderRadius: theme.radii.md,
              background: theme.colors.dangerSoft,
              color: theme.colors.danger,
              border: `1px solid ${theme.colors.danger}`,
              fontWeight: theme.typography.fontWeightMedium,
            }}
          >
            {error}
          </div>
        ) : null}

        <p style={{ margin: 0, color: theme.colors.textMuted }}>
          This mirrors running <code>onepiece render submit</code> from the CLI.
        </p>
      </div>
    </Modal>
  );
}

export default SubmitRenderModal;
