import React, { useEffect, useState } from 'react';
import { Button, Card, SectionHeader, TextInput, useToast } from './ui';
import { useTheme } from '../styles/ThemeContext';

type ProfileOption = 'vfx' | 'archviz' | 'freelancer' | 'demo' | '';
type DccKey = 'maya' | 'blender' | 'unreal';

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
};

type UpdateCheckResult = {
  hasUpdate: boolean;
  latestVersion?: string;
  url?: string;
  error?: string;
  currentVersion?: string;
};

declare global {
  interface Window {
    electron: {
      invoke: <T = unknown>(channel: string, payload?: unknown) => Promise<T>;
    };
  }
}

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

        setConfig(loaded);
        setForm({
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
        });
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
