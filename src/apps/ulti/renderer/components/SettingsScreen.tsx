import React, { useEffect, useState } from 'react';

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
};

function SettingsScreen({ onRequestRerunWizard }: SettingsScreenProps): JSX.Element {
  const [config, setConfig] = useState<DesktopConfig | null>(null);
  const [form, setForm] = useState<FormState>(defaultForm);
  const [loading, setLoading] = useState<boolean>(true);
  const [saving, setSaving] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
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
    setSuccess(null);

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

    if (Object.keys(updates).length === 0) {
      setSuccess('No changes to save.');
      return;
    }

    setSaving(true);
    try {
      const updatedConfig = await window.electron.invoke<DesktopConfig>('config/save', updates);
      setConfig(updatedConfig);
      setSuccess('Settings saved successfully.');
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
    <div className="op-field-group" key={key}>
      <label className="op-checkbox">
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
      <label className="op-field">
        <span>Executable path</span>
        <input
          type="text"
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
          placeholder={`Path to ${label} executable`}
        />
      </label>
    </div>
  );

  if (loading) {
    return <div className="op-loading">Loading settings…</div>;
  }

  return (
    <div className="op-layout">
      <header className="op-header">
        <div>
          <p className="op-eyebrow">OnePiece Studio Desktop</p>
          <h1>Settings</h1>
          <p>Update your configuration, integrations, and DCC preferences.</p>
        </div>
        <button type="button" className="op-secondary" onClick={() => void handleSave()} disabled={saving}>
          {saving ? 'Saving…' : 'Save changes'}
        </button>
      </header>

      {error ? (
        <div className="op-banner op-banner-error">
          <div>
            <strong>Something went wrong</strong>
            <p className="op-banner-message">{error}</p>
          </div>
          <button type="button" className="op-tertiary" onClick={() => setError(null)}>
            Dismiss
          </button>
        </div>
      ) : null}

      {success ? (
        <div className="op-banner op-banner-success">
          <p className="op-banner-message">{success}</p>
          <button type="button" className="op-tertiary" onClick={() => setSuccess(null)}>
            Dismiss
          </button>
        </div>
      ) : null}

      <div className="op-grid">
        <section className="op-card">
          <h2>Profile</h2>
          <label className="op-field">
            <span>Usage profile</span>
            <select
              value={form.profile}
              onChange={(event) => setForm((prev) => ({ ...prev, profile: event.target.value as ProfileOption }))}
            >
              <option value="">Select a profile</option>
              <option value="vfx">VFX studio</option>
              <option value="archviz">Archviz studio</option>
              <option value="freelancer">Freelancer</option>
              <option value="demo">Demo / testing</option>
            </select>
          </label>
        </section>

        <section className="op-card">
          <h2>Paths</h2>
          <div className="op-field-group">
            <label className="op-field required">
              <span>Project root</span>
              <input
                type="text"
                value={form.projectRoot}
                onChange={(event) => setForm((prev) => ({ ...prev, projectRoot: event.target.value }))}
                placeholder="/path/to/your/project"
                required
              />
            </label>
            <label className="op-field">
              <span>Python path (optional)</span>
              <input
                type="text"
                value={form.pythonPath}
                onChange={(event) => setForm((prev) => ({ ...prev, pythonPath: event.target.value }))}
                placeholder="Path to python executable"
              />
            </label>
          </div>
        </section>
      </div>

      <div className="op-grid">
        <section className="op-card">
          <h2>Integrations</h2>
          <div className="op-subsection">
            <h3>ShotGrid</h3>
            <div className="op-field-group">
              <label className="op-field">
                <span>URL</span>
                <input
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
              </label>
              <label className="op-field">
                <span>Script name</span>
                <input
                  type="text"
                  value={form.shotgrid.scriptName}
                  onChange={(event) =>
                    setForm((prev) => ({
                      ...prev,
                      shotgrid: { ...prev.shotgrid, scriptName: event.target.value },
                    }))
                  }
                  placeholder="Your script name"
                />
              </label>
              <label className="op-field">
                <span>API key</span>
                <input
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
              </label>
            </div>
          </div>

          <div className="op-subsection">
            <h3>AWS</h3>
            <div className="op-field-group">
              <label className="op-field">
                <span>Access key ID</span>
                <input
                  type="text"
                  value={form.aws.accessKeyId}
                  onChange={(event) =>
                    setForm((prev) => ({
                      ...prev,
                      aws: { ...prev.aws, accessKeyId: event.target.value },
                    }))
                  }
                  placeholder="AWS access key ID"
                />
              </label>
              <label className="op-field">
                <span>Secret access key</span>
                <input
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
              </label>
              <label className="op-field">
                <span>Region</span>
                <input
                  type="text"
                  value={form.aws.region}
                  onChange={(event) =>
                    setForm((prev) => ({
                      ...prev,
                      aws: { ...prev.aws, region: event.target.value },
                    }))
                  }
                  placeholder="us-west-2"
                />
              </label>
              <label className="op-field">
                <span>Default bucket</span>
                <input
                  type="text"
                  value={form.aws.defaultBucket}
                  onChange={(event) =>
                    setForm((prev) => ({
                      ...prev,
                      aws: { ...prev.aws, defaultBucket: event.target.value },
                    }))
                  }
                  placeholder="my-bucket"
                />
              </label>
            </div>
          </div>
        </section>

        <section className="op-card">
          <h2>DCCs</h2>
          {renderDccRow('maya', 'Maya')}
          {renderDccRow('blender', 'Blender')}
          {renderDccRow('unreal', 'Unreal Engine')}
        </section>
      </div>

      <section className="op-card">
        <h2>Updates</h2>
        <p>Check for a newer version of OnePiece Studio Desktop.</p>
        <div className="op-actions">
          <button
            type="button"
            className="op-secondary"
            onClick={() => void handleCheckForUpdates()}
            disabled={checkingUpdate}
          >
            {checkingUpdate ? 'Checking…' : 'Check for updates'}
          </button>
        </div>
        {updateStatus ? (
          <div className="op-banner" style={{ marginTop: '1rem' }}>
            {updateStatus.error ? (
              <p className="op-banner-message">Could not check for updates.</p>
            ) : updateStatus.hasUpdate ? (
              <div>
                <strong>New version available: v{updateStatus.latestVersion}</strong>
                {updateStatus.url ? (
                  <div>
                    <button
                      type="button"
                      className="op-tertiary"
                      onClick={() => void window.electron.invoke('open-url', { url: updateStatus.url })}
                    >
                      View release
                    </button>
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
      </section>

      <div className="op-actions">
        <button type="button" className="op-primary" onClick={() => void handleSave()} disabled={saving}>
          {saving ? 'Saving…' : 'Save changes'}
        </button>
        <button type="button" className="op-secondary" onClick={() => void confirmRerunWizard()}>
          Re-run setup wizard
        </button>
      </div>
    </div>
  );
}

export default SettingsScreen;
