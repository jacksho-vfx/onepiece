import React, { useEffect, useMemo, useState } from 'react';
import { Button, Card, SectionHeader, StatusBadge, TextInput, useToast } from './ui';
import { useTheme } from '../styles/ThemeContext';
import {
  buildRemoteFromParts,
  normalizeAwsSyncPresets,
  normalizeBucketUrl,
  parseRemoteParts,
  type AwsSyncPresetInput,
} from './tools/awsSyncPresets';

type ProfileOption = 'vfx' | 'archviz' | 'freelancer' | 'demo' | '';
type DccKey = 'maya' | 'blender' | 'unreal';
type DetectedEnv = {
  dccs?: Partial<Record<DccKey, string>>;
};

type ShotgridConfig = {
  url?: string;
  scriptName?: string;
  apiKey?: string;
};

type AwsConfig = {
  accessKeyId?: string;
  secretAccessKey?: string;
  region?: string;
  defaultBucket?: string;
};

type DccConfig = {
  enabled: boolean;
  executablePath?: string;
};

type DesktopConfig = {
  hasCompletedWizard: boolean;
  createdAt: string;
  updatedAt: string;
  enableNotifications?: boolean;
  profile?: 'vfx' | 'archviz' | 'freelancer' | 'demo';
  pythonPath?: string;
  projectRoot?: string;
  shotgrid?: ShotgridConfig;
  aws?: AwsConfig;
  dccs?: Record<DccKey, DccConfig>;
  services?: {
    profiles: {
      key: string;
      name: string;
      description: string;
      args: string[];
      persistent?: boolean;
    }[];
    enabled?: Record<string, boolean>;
  };
  awsSyncPresets?: {
    id: string;
    name: string;
    direction: 'from' | 'to' | 'download' | 'upload';
    localPath: string;
    bucketUrl: string;
    showCode?: string;
    remotePath?: string;
    remote?: string;
  }[];
};

type FormState = {
  profile: ProfileOption;
  projectRoot: string;
  pythonPath: string;
  shotgrid: Required<ShotgridConfig>;
  aws: Required<AwsConfig>;
  dccs: Record<DccKey, DccConfig>;
  enableNotifications: boolean;
};

type SettingsScreenProps = {
  onRequestRerunWizard: () => void;
  onConfigImported?: () => Promise<void> | void;
};

const DCC_LABELS: Record<DccKey, string> = {
  maya: 'Maya',
  blender: 'Blender',
  unreal: 'Unreal Engine',
};

type UpdateCheckResult = {
  hasUpdate: boolean;
  latestVersion?: string;
  url?: string;
  error?: string;
  currentVersion?: string;
};

const defaultForm: FormState = {
  profile: '',
  projectRoot: '',
  pythonPath: '',
  shotgrid: {
    url: '',
    scriptName: '',
    apiKey: '',
  },
  aws: {
    accessKeyId: '',
    secretAccessKey: '',
    region: '',
    defaultBucket: '',
  },
  dccs: {
    maya: { enabled: false, executablePath: '' },
    blender: { enabled: false, executablePath: '' },
    unreal: { enabled: false, executablePath: '' },
  },
  enableNotifications: true,
};

type AwsSyncPresetForm = {
  id: string;
  name: string;
  direction: 'from' | 'to';
  localPath: string;
  bucketUrl: string;
  showCode: string;
  remotePath: string;
};

const defaultPresetForm: AwsSyncPresetForm = {
  id: '',
  name: '',
  direction: 'from',
  localPath: '',
  bucketUrl: '',
  showCode: '',
  remotePath: '',
};

function applyDetectedDccs(
  baseForm: FormState,
  detected?: Partial<Record<DccKey, string>>,
): { form: FormState; applied: DccKey[] } {
  if (!detected) {
    return { form: baseForm, applied: [] };
  }

  const applied: DccKey[] = [];
  const nextForm: FormState = {
    ...baseForm,
    dccs: { ...baseForm.dccs },
  };

  (Object.keys(detected) as DccKey[]).forEach((key) => {
    const detectedPath = detected[key];
    if (!detectedPath) {
      return;
    }

    const currentPath = nextForm.dccs[key].executablePath?.trim();
    const hasUserValue = Boolean(currentPath);

    if (!hasUserValue) {
      applied.push(key);
      nextForm.dccs[key] = {
        enabled: true,
        executablePath: detectedPath,
      };
    }
  });

  return { form: nextForm, applied };
}

function SettingsScreen({ onRequestRerunWizard }: SettingsScreenProps): JSX.Element {
  const theme = useTheme();
  const { showToast } = useToast();
  const [config, setConfig] = useState<DesktopConfig | null>(null);
  const [form, setForm] = useState<FormState>(defaultForm);
  const [loading, setLoading] = useState<boolean>(true);
  const [saving, setSaving] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [desktopVersion, setDesktopVersion] = useState<string | null>(null);
  const [updateStatus, setUpdateStatus] = useState<UpdateCheckResult | null>(null);
  const [checkingUpdate, setCheckingUpdate] = useState<boolean>(false);
  const [exportingConfig, setExportingConfig] = useState<boolean>(false);
  const [importingConfig, setImportingConfig] = useState<boolean>(false);
  const [dccDetectionMessage, setDccDetectionMessage] = useState<string | null>(null);
  const [awsSyncPresets, setAwsSyncPresets] = useState<AwsSyncPresetInput[]>([]);
  const [presetForm, setPresetForm] = useState<AwsSyncPresetForm>(defaultPresetForm);
  const [presetError, setPresetError] = useState<string | null>(null);
  const [savingPreset, setSavingPreset] = useState<boolean>(false);

  const buildPresetForm = (
    preset?: AwsSyncPresetInput,
    bucketFallback?: string,
  ): AwsSyncPresetForm => {
    const parsed = preset ? parseRemoteParts(preset.remote ?? preset.bucketUrl) : {};
    const bucketUrl = normalizeBucketUrl(
      preset?.bucketUrl ?? parsed.bucketUrl ?? bucketFallback ?? form.aws.defaultBucket,
    );

    const direction: 'from' | 'to' = preset?.direction === 'upload'
      ? 'to'
      : preset?.direction === 'download'
        ? 'from'
        : (preset?.direction as 'from' | 'to' | undefined) ?? 'from';

    return {
      id: preset?.id ?? '',
      name: preset?.name ?? '',
      direction,
      localPath: preset?.localPath ?? '',
      bucketUrl: bucketUrl || '',
      showCode: preset?.showCode ?? parsed.showCode ?? '',
      remotePath: preset?.remotePath ?? parsed.remotePath ?? '',
    };
  };

  const resetPresetForm = (bucketFallback?: string): void => {
    setPresetForm(buildPresetForm(undefined, bucketFallback));
    setPresetError(null);
  };

  useEffect(() => {
    let mounted = true;

    const fetchVersions = async (): Promise<void> => {
      try {
        const versions = await window.electron.invoke<{ desktop: string; onepiece: string | null }>('version/get');
        if (mounted) {
          setDesktopVersion(versions.desktop);
        }
      } catch (err) {
        console.error('Failed to load version info', err);
      }
    };

    const fetchConfig = async (): Promise<void> => {
      try {
        const loaded = await window.electron.invoke<DesktopConfig>('config/get');
        if (!mounted) return;

        let nextForm: FormState = {
          profile: loaded.profile ?? '',
          projectRoot: loaded.projectRoot ?? '',
          pythonPath: loaded.pythonPath ?? '',
          enableNotifications: loaded.enableNotifications ?? true,
          shotgrid: {
            url: loaded.shotgrid?.url ?? '',
            scriptName: loaded.shotgrid?.scriptName ?? '',
            apiKey: loaded.shotgrid?.apiKey ?? '',
          },
          aws: {
            accessKeyId: loaded.aws?.accessKeyId ?? '',
            secretAccessKey: loaded.aws?.secretAccessKey ?? '',
            region: loaded.aws?.region ?? '',
            defaultBucket: loaded.aws?.defaultBucket ?? '',
          },
          dccs: {
            maya: {
              enabled: loaded.dccs?.maya?.enabled ?? false,
              executablePath: loaded.dccs?.maya?.executablePath ?? '',
            },
            blender: {
              enabled: loaded.dccs?.blender?.enabled ?? false,
              executablePath: loaded.dccs?.blender?.executablePath ?? '',
            },
            unreal: {
              enabled: loaded.dccs?.unreal?.enabled ?? false,
              executablePath: loaded.dccs?.unreal?.executablePath ?? '',
            },
          },
        };

        setDccDetectionMessage(null);

        try {
          const env = await window.electron.invoke<DetectedEnv | null>('system/detect-env');

          const { form: formWithDetected, applied } = applyDetectedDccs(nextForm, env?.dccs);
          nextForm = formWithDetected;

          if (applied.length > 0) {
            const readableList = applied.map((key) => DCC_LABELS[key]).join(', ');
            setDccDetectionMessage(
              `We detected ${readableList}. Confirm or update these paths before saving.`,
            );
          } else {
            setDccDetectionMessage(null);
          }
        } catch (detectionError) {
          console.error('Failed to detect DCC executables', detectionError);
        }

        if (!mounted) return;

        setConfig(loaded);
        setForm(nextForm);
        setAwsSyncPresets(loaded.awsSyncPresets ?? []);
        resetPresetForm(loaded.aws?.defaultBucket);
      } catch (err) {
        if (!mounted) return;
        console.error('Failed to load config', err);
        setError('Unable to load settings.');
      } finally {
        if (mounted) setLoading(false);
      }
    };

    void fetchVersions();
    void fetchConfig();

    return () => {
      mounted = false;
    };
  }, []);

  useEffect(() => {
    if (presetForm.bucketUrl || !form.aws.defaultBucket) {
      return;
    }

    setPresetForm((prev) => ({ ...prev, bucketUrl: normalizeBucketUrl(form.aws.defaultBucket) }));
  }, [form.aws.defaultBucket, presetForm.bucketUrl]);

  const normalizeString = (value: string): string | undefined => {
    const trimmed = value.trim();
    return trimmed ? trimmed : undefined;
  };

  const handleSave = async (): Promise<void> => {
    setError(null);

    if (!form.projectRoot.trim()) {
      setError('Project root is required.');
      return;
    }

    if (!config) {
      setError('Configuration is still loading.');
      return;
    }

    const updates: Partial<DesktopConfig> = {};

    const nextProfile = form.profile || undefined;
    if (nextProfile !== config.profile) {
      updates.profile = nextProfile;
    }

    if (form.projectRoot.trim() !== (config.projectRoot ?? '')) {
      updates.projectRoot = form.projectRoot.trim();
    }

    const nextPythonPath = normalizeString(form.pythonPath);
    if (nextPythonPath !== (config.pythonPath ?? undefined)) {
      updates.pythonPath = nextPythonPath;
    }

    const nextShotgrid: ShotgridConfig = {
      url: normalizeString(form.shotgrid.url),
      scriptName: normalizeString(form.shotgrid.scriptName),
      apiKey: normalizeString(form.shotgrid.apiKey),
    };

    const shotgridChanged =
      nextShotgrid.url !== (config.shotgrid?.url ?? undefined) ||
      nextShotgrid.scriptName !== (config.shotgrid?.scriptName ?? undefined) ||
      nextShotgrid.apiKey !== (config.shotgrid?.apiKey ?? undefined);

    if (shotgridChanged) {
      updates.shotgrid = { ...config.shotgrid, ...nextShotgrid };
    }

    const nextAws: AwsConfig = {
      accessKeyId: normalizeString(form.aws.accessKeyId),
      secretAccessKey: normalizeString(form.aws.secretAccessKey),
      region: normalizeString(form.aws.region),
      defaultBucket: normalizeString(form.aws.defaultBucket),
    };

    const awsChanged =
      nextAws.accessKeyId !== (config.aws?.accessKeyId ?? undefined) ||
      nextAws.secretAccessKey !== (config.aws?.secretAccessKey ?? undefined) ||
      nextAws.region !== (config.aws?.region ?? undefined) ||
      nextAws.defaultBucket !== (config.aws?.defaultBucket ?? undefined);

    if (awsChanged) {
      updates.aws = { ...config.aws, ...nextAws };
    }

    const changedDccs: Partial<Record<DccKey, DccConfig>> = {};
    (['maya', 'blender', 'unreal'] as DccKey[]).forEach((key) => {
      const next = {
        enabled: form.dccs[key].enabled,
        executablePath: normalizeString(form.dccs[key].executablePath),
      };

      const current = config.dccs?.[key];
      if (!current || current.enabled !== next.enabled || current.executablePath !== next.executablePath) {
        changedDccs[key] = next;
      }
    });

    if (Object.keys(changedDccs).length > 0) {
      updates.dccs = { ...config.dccs, ...changedDccs };
    }

    if ((config.enableNotifications ?? true) !== form.enableNotifications) {
      updates.enableNotifications = form.enableNotifications;
    }

    if (Object.keys(updates).length === 0) {
      showToast({ kind: 'info', message: 'No changes to save.' });
      return;
    }

    setSaving(true);
    try {
      const updatedConfig = await window.electron.invoke<DesktopConfig>('config/save', updates);
      setConfig(updatedConfig);
      showToast({ kind: 'success', message: 'Settings saved' });
    } catch (err) {
      console.error('Failed to save settings', err);
      setError(err instanceof Error ? err.message : 'Failed to save settings.');
    } finally {
      setSaving(false);
    }
  };

  const normalizedPresets = useMemo(
    () => normalizeAwsSyncPresets(awsSyncPresets, form.aws.defaultBucket),
    [awsSyncPresets, form.aws.defaultBucket],
  );

  const handlePresetSelect = (presetId: string): void => {
    const selected = awsSyncPresets.find((preset) => preset.id === presetId);
    setPresetForm(buildPresetForm(selected));
    setPresetError(null);
  };

  const handlePresetSave = async (): Promise<void> => {
    setPresetError(null);

    const name = presetForm.name.trim();
    const localPath = presetForm.localPath.trim();
    const showCode = presetForm.showCode.trim();
    const remotePath = presetForm.remotePath.trim();
    const resolvedBucket = normalizeBucketUrl(presetForm.bucketUrl || form.aws.defaultBucket);

    if (!name) {
      setPresetError('Give the preset a name.');
      return;
    }

    if (!localPath) {
      setPresetError('Enter the local path to sync.');
      return;
    }

    if (!resolvedBucket) {
      setPresetError('Enter a bucket or set a default bucket in AWS settings.');
      return;
    }

    if (!showCode) {
      setPresetError('Enter the show code to sync.');
      return;
    }

    if (!remotePath) {
      setPresetError('Enter the folder/path within the show.');
      return;
    }

    const presetId = presetForm.id || `aws-sync-${Date.now().toString(16)}`;
    const direction: AwsSyncPresetInput['direction'] = presetForm.direction === 'to' ? 'to' : 'from';
    const remote = buildRemoteFromParts({ bucketUrl: resolvedBucket, showCode, remotePath });

    const nextPreset: AwsSyncPresetInput = {
      id: presetId,
      name,
      direction,
      localPath,
      bucketUrl: resolvedBucket,
      showCode,
      remotePath,
      remote,
    };

    const nextPresets = [...awsSyncPresets.filter((preset) => preset.id !== presetId), nextPreset];

    setSavingPreset(true);

    try {
      const updatedConfig = await window.electron.invoke<DesktopConfig>('config/save', {
        awsSyncPresets: nextPresets,
      });

      setConfig(updatedConfig);
      setAwsSyncPresets(updatedConfig.awsSyncPresets ?? []);
      setPresetForm(buildPresetForm(nextPreset, updatedConfig.aws?.defaultBucket));
      showToast({ kind: 'success', message: 'AWS sync preset saved.' });
    } catch (err) {
      console.error('Failed to save AWS sync preset', err);
      setPresetError(err instanceof Error ? err.message : 'Could not save preset.');
    } finally {
      setSavingPreset(false);
    }
  };

  const handlePresetDelete = async (presetId: string): Promise<void> => {
    if (!presetId) {
      setPresetError('Select a preset to delete.');
      return;
    }

    const remaining = awsSyncPresets.filter((preset) => preset.id !== presetId);
    setSavingPreset(true);

    try {
      const updatedConfig = await window.electron.invoke<DesktopConfig>('config/save', {
        awsSyncPresets: remaining,
      });

      setConfig(updatedConfig);
      setAwsSyncPresets(updatedConfig.awsSyncPresets ?? []);
      resetPresetForm(updatedConfig.aws?.defaultBucket);
      showToast({ kind: 'success', message: 'Preset deleted.' });
    } catch (err) {
      console.error('Failed to delete AWS sync preset', err);
      setPresetError(err instanceof Error ? err.message : 'Could not delete preset.');
    } finally {
      setSavingPreset(false);
    }
  };

  const handleExportConfigBundle = async (): Promise<void> => {
    setExportingConfig(true);

    try {
      const exportedPath = await window.electron.invoke<string>('config/export-bundle');
      if (!exportedPath) {
        throw new Error('No path was returned for the exported bundle.');
      }
      showToast({ kind: 'success', message: `Exported config to ${exportedPath}` });
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to export config bundle.';
      showToast({
        kind: message.toLowerCase().includes('cancel') ? 'info' : 'error',
        message,
      });
    } finally {
      setExportingConfig(false);
    }
  };

  const handleImportConfigBundle = async (): Promise<void> => {
    setImportingConfig(true);

    try {
      await window.electron.invoke('config/import-bundle');
      showToast({ kind: 'success', message: 'Imported studio configuration. Please restart the app.' });
      await onConfigImported?.();
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to import config bundle.';
      showToast({
        kind: message.toLowerCase().includes('cancel') ? 'info' : 'error',
        message,
      });
    } finally {
      setImportingConfig(false);
    }
  };

  const handleCheckForUpdates = async (): Promise<void> => {
    setUpdateStatus(null);
    setCheckingUpdate(true);

    try {
      const result = await window.electron.invoke<UpdateCheckResult>('updates/check');
      setUpdateStatus(result);
      if (result.currentVersion && !desktopVersion) {
        setDesktopVersion(result.currentVersion);
      }
    } catch (err) {
      setUpdateStatus({
        hasUpdate: false,
        error: err instanceof Error ? err.message : 'Unable to check for updates.',
      });
    } finally {
      setCheckingUpdate(false);
    }
  };

  const confirmRerunWizard = async (): Promise<void> => {
    const confirmed = window.confirm('Re-run the setup wizard? This will guide you through configuration again.');
    if (!confirmed) return;

    try {
      await window.electron.invoke('config/save', { hasCompletedWizard: false });
      onRequestRerunWizard();
    } catch (err) {
      console.error('Failed to reset wizard state', err);
      setError(err instanceof Error ? err.message : 'Unable to re-run wizard.');
    }
  };

  const renderDccRow = (key: DccKey, label: string): JSX.Element => (
    <div key={key} style={{ display: 'grid', gap: theme.spacing.sm }}>
      <label style={{ display: 'flex', alignItems: 'center', gap: theme.spacing.sm }}>
        <input
          type="checkbox"
          checked={form.dccs[key].enabled}
          onChange={(event) =>
            setForm((prev) => ({
              ...prev,
              dccs: {
                ...prev.dccs,
                [key]: { ...prev.dccs[key], enabled: event.target.checked },
              },
            }))
          }
        />
        <span>{label} enabled</span>
      </label>
      <TextInput
        label="Executable path"
        placeholder={`Path to ${label} executable`}
        value={form.dccs[key].executablePath}
        onChange={(event) =>
          setForm((prev) => ({
            ...prev,
            dccs: {
              ...prev.dccs,
              [key]: { ...prev.dccs[key], executablePath: event.target.value },
            },
          }))
        }
      />
    </div>
  );

  if (loading) {
    return <div className="op-loading">Loading settings…</div>;
  }

  return (
    <div className="op-layout" style={{ display: 'flex', flexDirection: 'column', gap: theme.spacing.lg }}>
      <SectionHeader
        title="Settings"
        subtitle="Update your configuration, integrations, and DCC preferences."
      />

      {error ? (
        <div className="op-banner op-banner-error">
          <div>
            <strong>Something went wrong</strong>
            <p className="op-banner-message">{error}</p>
          </div>
          <Button variant="ghost" onClick={() => setError(null)}>
            Dismiss
          </Button>
        </div>
      ) : null}

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))',
          gap: theme.spacing.lg,
        }}
      >
        <Card title="Profile">
          <label style={{ display: 'grid', gap: '0.35rem', color: theme.colors.text }}>
            <span style={{ fontWeight: theme.typography.fontWeightMedium }}>Usage profile</span>
            <select
              value={form.profile}
              onChange={(event) => setForm((prev) => ({ ...prev, profile: event.target.value as ProfileOption }))}
              style={{
                padding: `${theme.spacing.sm} ${theme.spacing.md}`,
                borderRadius: theme.radii.md,
                border: `1px solid ${theme.colors.border}`,
                background: theme.colors.surfaceAlt,
                color: theme.colors.text,
              }}
            >
              <option value="">Select a profile</option>
              <option value="vfx">VFX studio</option>
              <option value="archviz">Archviz studio</option>
              <option value="freelancer">Freelancer</option>
              <option value="demo">Demo / testing</option>
            </select>
          </label>
        </Card>

        <Card title="Paths">
          <div style={{ display: 'grid', gap: theme.spacing.sm }}>
            <TextInput
              label="Project root"
              value={form.projectRoot}
              onChange={(event) => setForm((prev) => ({ ...prev, projectRoot: event.target.value }))}
              placeholder="/path/to/your/project"
              required
            />
            <TextInput
              label="Python path (optional)"
              value={form.pythonPath}
              onChange={(event) => setForm((prev) => ({ ...prev, pythonPath: event.target.value }))}
              placeholder="Path to python executable"
            />
          </div>
        </Card>

        <Card title="Notifications">
          <div style={{ display: 'grid', gap: theme.spacing.md }}>
            <p style={{ margin: 0, color: theme.colors.textMuted }}>
              Enable desktop notifications when background tasks complete.
            </p>
            <label style={{ display: 'flex', alignItems: 'center', gap: theme.spacing.sm }}>
              <input
                type="checkbox"
                checked={form.enableNotifications}
                onChange={(event) =>
                  setForm((prev) => ({ ...prev, enableNotifications: event.target.checked }))
                }
              />
              <span>Desktop notifications for task completion</span>
            </label>
          </div>
        </Card>
      </div>

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))',
          gap: theme.spacing.lg,
        }}
      >
        <Card title="Integrations">
          <div style={{ display: 'grid', gap: theme.spacing.lg }}>
            <div style={{ display: 'grid', gap: theme.spacing.sm }}>
              <h3 style={{ margin: 0 }}>ShotGrid</h3>
              <div style={{ display: 'grid', gap: theme.spacing.sm }}>
                <TextInput
                  label="URL"
                  type="url"
                  value={form.shotgrid.url}
                  onChange={(event) =>
                    setForm((prev) => ({
                      ...prev,
                      shotgrid: { ...prev.shotgrid, url: event.target.value },
                    }))
                  }
                  placeholder="https://your-site.shotgrid.autodesk.com"
                />
                <TextInput
                  label="Script name"
                  value={form.shotgrid.scriptName}
                  onChange={(event) =>
                    setForm((prev) => ({
                      ...prev,
                      shotgrid: { ...prev.shotgrid, scriptName: event.target.value },
                    }))
                  }
                  placeholder="Your script name"
                />
                <TextInput
                  label="API key"
                  type="password"
                  value={form.shotgrid.apiKey}
                  onChange={(event) =>
                    setForm((prev) => ({
                      ...prev,
                      shotgrid: { ...prev.shotgrid, apiKey: event.target.value },
                    }))
                  }
                  placeholder="Script API key"
                />
              </div>
            </div>

            <div
              style={{
                display: 'grid',
                gap: theme.spacing.sm,
                padding: theme.spacing.sm,
                borderRadius: theme.radii.md,
                border: `1px solid ${theme.colors.border}`,
                background: theme.colors.surfaceAlt,
              }}
            >
              <h3 style={{ margin: 0 }}>AWS Sync presets</h3>
              <p style={{ margin: 0, color: theme.colors.textMuted }}>
                Define reusable AWS sync presets without editing JSON. These presets appear in the AWS
                Sync tool so artists can trigger them quickly.
              </p>

              <div style={{ display: 'grid', gap: theme.spacing.sm }}>
                {normalizedPresets.length === 0 ? (
                  <p style={{ margin: 0, color: theme.colors.textMuted }}>No presets saved yet.</p>
                ) : (
                  normalizedPresets.map((preset) => (
                    <button
                      key={preset.id}
                      type="button"
                      onClick={() => handlePresetSelect(preset.id)}
                      style={{
                        textAlign: 'left',
                        padding: theme.spacing.sm,
                        borderRadius: theme.radii.md,
                        border: `1px solid ${theme.colors.border}`,
                        background: theme.colors.surface,
                        cursor: 'pointer',
                      }}
                    >
                      <div style={{ display: 'flex', gap: theme.spacing.sm, alignItems: 'center' }}>
                        <strong>{preset.name}</strong>
                        <StatusBadge status={preset.direction === 'upload' ? 'Warning' : 'Default'}>
                          {preset.direction === 'upload' ? 'Upload' : 'Download'}
                        </StatusBadge>
                      </div>
                      <div className="op-muted" style={{ display: 'grid', gap: 2 }}>
                        <span>Remote: {preset.remote || 'Not configured'}</span>
                        <span>Local: {preset.localPath}</span>
                      </div>
                    </button>
                  ))
                )}
              </div>

              <div style={{ display: 'grid', gap: theme.spacing.sm }}>
                <TextInput
                  label="Preset name"
                  value={presetForm.name}
                  onChange={(event) => setPresetForm((prev) => ({ ...prev, name: event.target.value }))}
                  placeholder="Daily upload"
                />

                <label style={{ display: 'grid', gap: '0.35rem' }}>
                  <span style={{ fontWeight: theme.typography.fontWeightMedium }}>Direction</span>
                  <select
                    value={presetForm.direction}
                    onChange={(event) =>
                      setPresetForm((prev) => ({ ...prev, direction: event.target.value as AwsSyncPresetForm['direction'] }))
                    }
                    style={{
                      padding: `${theme.spacing.sm} ${theme.spacing.md}`,
                      borderRadius: theme.radii.md,
                      border: `1px solid ${theme.colors.border}`,
                      background: theme.colors.surface,
                    }}
                  >
                    <option value="from">Download (S3 → local)</option>
                    <option value="to">Upload (local → S3)</option>
                  </select>
                </label>

                <TextInput
                  label="Local path"
                  value={presetForm.localPath}
                  onChange={(event) =>
                    setPresetForm((prev) => ({ ...prev, localPath: event.target.value }))
                  }
                  placeholder="/projects/show/cache"
                  required
                />

                <div
                  style={{
                    display: 'grid',
                    gap: theme.spacing.sm,
                    gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
                  }}
                >
                  <TextInput
                    label="Bucket"
                    value={presetForm.bucketUrl}
                    onChange={(event) =>
                      setPresetForm((prev) => ({ ...prev, bucketUrl: event.target.value }))
                    }
                    placeholder={form.aws.defaultBucket || 's3://my-bucket'}
                  />
                  <TextInput
                    label="Show code"
                    value={presetForm.showCode}
                    onChange={(event) =>
                      setPresetForm((prev) => ({ ...prev, showCode: event.target.value }))
                    }
                    placeholder="show"
                  />
                  <TextInput
                    label="Path / prefix"
                    value={presetForm.remotePath}
                    onChange={(event) =>
                      setPresetForm((prev) => ({ ...prev, remotePath: event.target.value }))
                    }
                    placeholder="renders/shot01"
                  />
                </div>

                <p style={{ margin: 0, color: theme.colors.textMuted }}>
                  Remote preview:{' '}
                  {buildRemoteFromParts({
                    bucketUrl: presetForm.bucketUrl || form.aws.defaultBucket,
                    showCode: presetForm.showCode,
                    remotePath: presetForm.remotePath,
                  }) || 'Add a bucket, show, and path to preview'}
                </p>

                {presetError ? (
                  <p style={{ margin: 0, color: theme.colors.danger }}>{presetError}</p>
                ) : null}

                <div style={{ display: 'flex', gap: theme.spacing.sm, flexWrap: 'wrap' }}>
                  <Button onClick={() => void handlePresetSave()} isLoading={savingPreset} disabled={savingPreset}>
                    Save preset
                  </Button>
                  <Button variant="secondary" onClick={() => resetPresetForm()} disabled={savingPreset}>
                    Reset form
                  </Button>
                  <Button
                    variant="secondary"
                    onClick={() => void handlePresetDelete(presetForm.id)}
                    disabled={!presetForm.id || savingPreset}
                  >
                    Delete preset
                  </Button>
                </div>
              </div>
            </div>

            <div style={{ display: 'grid', gap: theme.spacing.sm }}>
              <h3 style={{ margin: 0 }}>AWS</h3>
              <div style={{ display: 'grid', gap: theme.spacing.sm }}>
                <TextInput
                  label="Access key ID"
                  value={form.aws.accessKeyId}
                  onChange={(event) =>
                    setForm((prev) => ({
                      ...prev,
                      aws: { ...prev.aws, accessKeyId: event.target.value },
                    }))
                  }
                  placeholder="AWS access key ID"
                />
                <TextInput
                  label="Secret access key"
                  type="password"
                  value={form.aws.secretAccessKey}
                  onChange={(event) =>
                    setForm((prev) => ({
                      ...prev,
                      aws: { ...prev.aws, secretAccessKey: event.target.value },
                    }))
                  }
                  placeholder="AWS secret access key"
                />
                <TextInput
                  label="Region"
                  value={form.aws.region}
                  onChange={(event) =>
                    setForm((prev) => ({
                      ...prev,
                      aws: { ...prev.aws, region: event.target.value },
                    }))
                  }
                  placeholder="us-west-2"
                />
                <TextInput
                  label="Default bucket"
                  value={form.aws.defaultBucket}
                  onChange={(event) =>
                    setForm((prev) => ({
                      ...prev,
                      aws: { ...prev.aws, defaultBucket: event.target.value },
                    }))
                  }
                  placeholder="my-bucket"
                />
              </div>
            </div>
          </div>
        </Card>

        <Card title="DCCs">
          <p style={{ margin: 0, color: theme.colors.textMuted }}>
            Enable and point to your preferred digital content creation tools.
          </p>
          {dccDetectionMessage ? (
            <div className="op-banner" role="alert">
              <p className="op-banner-message" style={{ margin: 0 }}>
                {dccDetectionMessage}
              </p>
            </div>
          ) : null}
          <div style={{ display: 'grid', gap: theme.spacing.md }}>
            {renderDccRow('maya', 'Maya')}
            {renderDccRow('blender', 'Blender')}
            {renderDccRow('unreal', 'Unreal Engine')}
          </div>
        </Card>
      </div>

      <Card>
        <SectionHeader
          title="Updates"
          subtitle="Check for a newer version of OnePiece Studio Desktop."
          action={
            <Button
              variant="secondary"
              onClick={() => void handleCheckForUpdates()}
              isLoading={checkingUpdate}
              disabled={checkingUpdate}
            >
              {checkingUpdate ? 'Checking…' : 'Check for updates'}
            </Button>
          }
        />
        {updateStatus ? (
          <div className="op-banner" style={{ marginTop: '1rem' }}>
            {updateStatus.error ? (
              <p className="op-banner-message">Could not check for updates.</p>
            ) : updateStatus.hasUpdate ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: theme.spacing.sm }}>
                <strong>New version available: v{updateStatus.latestVersion}</strong>
                {updateStatus.url ? (
                  <div>
                    <Button
                      variant="secondary"
                      onClick={() => void window.electron.invoke('open-url', { url: updateStatus.url })}
                    >
                      View release
                    </Button>
                  </div>
                ) : null}
              </div>
            ) : (
              <p className="op-banner-message">
                You are up to date {desktopVersion ? `(v${desktopVersion})` : ''}
              </p>
            )}
          </div>
        ) : null}
      </Card>

      <Card>
        <SectionHeader
          title="Export studio config"
          subtitle="Download a bundle containing your desktop and project configuration files."
          action={
            <div style={{ display: 'flex', gap: theme.spacing.sm }}>
              <Button
                variant="secondary"
                onClick={() => void handleImportConfigBundle()}
                isLoading={importingConfig}
                disabled={importingConfig || exportingConfig}
              >
                {importingConfig ? 'Importing…' : 'Import config'}
              </Button>
              <Button
                variant="secondary"
                onClick={() => void handleExportConfigBundle()}
                isLoading={exportingConfig}
                disabled={exportingConfig || importingConfig}
              >
                {exportingConfig ? 'Exporting…' : 'Export config'}
              </Button>
            </div>
          }
        />
        <p style={{ marginTop: theme.spacing.md, color: theme.colors.textMuted }}>
          Use this to share your setup with teammates or support. The bundle includes your desktop
          preferences, the current project's <code>onepiece.toml</code>, and related configuration
          files.
        </p>
      </Card>

      <div style={{ display: 'flex', gap: theme.spacing.sm, justifyContent: 'flex-start' }}>
        <Button onClick={() => void handleSave()} isLoading={saving} disabled={saving}>
          {saving ? 'Saving…' : 'Save changes'}
        </Button>
        <Button variant="secondary" onClick={() => void confirmRerunWizard()}>
          Re-run setup wizard
        </Button>
      </div>
    </div>
  );
}

export default SettingsScreen;
