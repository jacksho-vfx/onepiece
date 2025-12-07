import React, { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import Card from './ui/Card';
import SectionHeader from './ui/SectionHeader';
import Button from './ui/Button';
import TextInput from './ui/TextInput';
import WizardStep from './ui/WizardStep';
import { designTokens, roleColors } from '../styles/designTokens';
import { useTheme } from '../styles/ThemeContext';
import { useToast } from './ui/Toaster';
import { hexToRgba } from './ui/styles';

type ProfileOption = 'vfx' | 'archviz' | 'freelancer' | 'demo' | '';

type DccAppKey = 'maya' | 'blender' | 'unreal';

interface ShotgridConfig {
  url?: string;
  scriptName?: string;
  apiKey?: string;
}

interface AwsConfig {
  accessKeyId?: string;
  secretAccessKey?: string;
  region?: string;
  defaultBucket?: string;
}

interface DccConfig {
  enabled: boolean;
  executablePath?: string;
}

interface WizardFormState {
  profile: ProfileOption;
  projectRoot: string;
  cacheLocation: string;
  pythonPath: string;
  shotgrid: ShotgridConfig;
  aws: AwsConfig;
  dcc: Record<DccAppKey, DccConfig>;
}

interface DesktopConfig {
  hasCompletedWizard: boolean;
  createdAt: string;
  updatedAt: string;
  profile?: 'vfx' | 'archviz' | 'freelancer' | 'demo';
  pythonPath?: string;
  projectRoot?: string;
  shotgrid?: ShotgridConfig;
  aws?: AwsConfig;
  cacheLocation?: string;
  dcc?: Record<DccAppKey, DccConfig>;
}

type WizardContextValue = {
  formData: WizardFormState;
  updateForm<K extends keyof WizardFormState>(key: K, value: WizardFormState[K]): void;
  updateNested<T extends keyof ShotgridConfig | keyof AwsConfig>(
    namespace: 'shotgrid' | 'aws',
    key: T,
    value: string,
  ): void;
  updateDcc(app: DccAppKey, updates: Partial<DccConfig>): void;
  detectionWarning: string | null;
};

const WizardFormContext = createContext<WizardContextValue | undefined>(undefined);

function useWizardForm(): WizardContextValue {
  const context = useContext(WizardFormContext);
  if (!context) {
    throw new Error('useWizardForm must be used within WizardFormProvider');
  }
  return context;
}

type FirstRunWizardProps = {
  onComplete: (options?: { openEnvironmentReport?: boolean }) => void;
};

const defaultFormState: WizardFormState = {
  profile: 'vfx',
  projectRoot: '',
  cacheLocation: '',
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
  dcc: {
    maya: { enabled: false, executablePath: '' },
    blender: { enabled: false, executablePath: '' },
    unreal: { enabled: false, executablePath: '' },
  },
};

type DetectedEnv = {
  pythonPathGuess?: string;
  dccs: Partial<Record<DccAppKey, string>>;
};

const detectionFailureMessage =
  'Automatic environment detection failed. Please enter your paths manually.';

function WizardFormProvider({ children }: { children: ReactNode }): JSX.Element {
  const [formData, setFormData] = useState<WizardFormState>(defaultFormState);
  const [detectionWarning, setDetectionWarning] = useState<string | null>(null);
  const { showToast } = useToast();

  useEffect(() => {
    let isMounted = true;

    const handleDetectionFailure = (): void => {
      if (!isMounted) {
        return;
      }

      setDetectionWarning(detectionFailureMessage);
      showToast({
        kind: 'error',
        message: detectionFailureMessage,
      });
    };

    const detectEnv = async (): Promise<void> => {
      try {
        const env = await window.electron.invoke<DetectedEnv | null>('system/detect-env');

        if (!isMounted) {
          return;
        }

        if (!env) {
          handleDetectionFailure();
          return;
        }

        const hasPythonGuess = Boolean(env.pythonPathGuess);
        const detectedDccs = env.dccs ?? {};
        const hasDccs = Object.values(detectedDccs).some(Boolean);

        if (!hasPythonGuess && !hasDccs) {
          handleDetectionFailure();
          return;
        }

        setFormData((prev) => {
          const nextDcc = { ...prev.dcc };

          (['maya', 'blender', 'unreal'] as DccAppKey[]).forEach((key) => {
            const detectedPath = env.dccs?.[key];
            const hasUserValue = prev.dcc[key].enabled || Boolean(prev.dcc[key].executablePath);

            if (detectedPath && !hasUserValue) {
              nextDcc[key] = {
                enabled: true,
                executablePath: detectedPath,
              };
            }
          });

          return {
            ...prev,
            pythonPath: prev.pythonPath || env.pythonPathGuess || '',
            dcc: nextDcc,
          };
        });
      } catch (error) {
        console.error('Failed to detect environment', error);
        handleDetectionFailure();
      }
    };

    void detectEnv();

    return () => {
      isMounted = false;
    };
  }, [showToast]);

  const updateForm = <K extends keyof WizardFormState>(key: K, value: WizardFormState[K]): void => {
    setFormData((prev) => ({
      ...prev,
      [key]: value,
    }));
  };

  const updateNested = (
    namespace: 'shotgrid' | 'aws',
    key: keyof ShotgridConfig | keyof AwsConfig,
    value: string,
  ): void => {
    setFormData((prev) => ({
      ...prev,
      [namespace]: {
        ...prev[namespace],
        [key]: value,
      },
    }));
  };

  const updateDcc = (app: DccAppKey, updates: Partial<DccConfig>): void => {
    setFormData((prev) => ({
      ...prev,
      dcc: {
        ...prev.dcc,
        [app]: {
          ...prev.dcc[app],
          ...updates,
        },
      },
    }));
  };

  const value = useMemo(
    () => ({ formData, updateForm, updateNested, updateDcc, detectionWarning }),
    [detectionWarning, formData],
  );

  return <WizardFormContext.Provider value={value}>{children}</WizardFormContext.Provider>;
}

const steps = [
  'Welcome',
  'Usage profile',
  'Project root & storage',
  'Integrations',
  'DCC selection',
  'Summary',
];

function StepIndicator({ currentStep }: { currentStep: number }): JSX.Element {
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

function WelcomeStep({ onNext }: { onNext: () => void }): JSX.Element {
  const theme = useTheme();

  return (
    <div style={{ display: 'grid', gap: theme.spacing.md }}>
      <div style={{ display: 'grid', gap: theme.spacing.sm }}>
        <h2 style={{ margin: 0, letterSpacing: '0.01em' }}>Welcome to OnePiece Studio Desktop</h2>
        <p style={{ margin: 0, color: theme.colors.textMuted }}>
          This guided setup will capture your workflow preferences, project storage locations, and optional integrations so we can
          configure the desktop experience for your studio.
        </p>
        <p style={{ margin: 0, color: theme.colors.textMuted }}>
          You can always experiment safely in the Tools tab using the Chopper Playground to inspect and render sample scenes without
          touching a DCC.
        </p>
      </div>
      <Button variant="primary" onClick={onNext} style={{ justifySelf: 'flex-start' }}>
        Get started
      </Button>
    </div>
  );
}

function UsageProfileStep({ error }: { error?: string }): JSX.Element {
  const { formData, updateForm } = useWizardForm();
  const theme = useTheme();
  const options: { label: string; value: ProfileOption; description: string }[] = [
    { label: 'VFX (recommended)', value: 'vfx', description: 'Best starting point for most studio pipelines.' },
    { label: 'Arch-viz', value: 'archviz', description: 'Defaults tuned for visualization workflows.' },
    { label: 'Freelancer', value: 'freelancer', description: 'Lightweight setup for solo artists.' },
    { label: 'Demo stack', value: 'demo', description: 'Use sample assets without touching DCCs.' },
  ];

  return (
    <div style={{ display: 'grid', gap: theme.spacing.md }}>
      <div style={{ display: 'grid', gap: theme.spacing.xs }}>
        <h3 style={{ margin: 0 }}>Tell us about your usage</h3>
        <p style={{ margin: 0, color: theme.colors.textMuted }}>
          We preselected the VFX profile to get you moving quickly. Pick another if it fits your day-to-day work better.
        </p>
      </div>
      <div
        style={{
          display: 'grid',
          gap: theme.spacing.sm,
        }}
      >
        {options.map((option) => {
          const isSelected = formData.profile === option.value;
          const isRecommended = option.value === 'vfx';
          return (
            <label
              key={option.value}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: theme.spacing.sm,
                padding: `${theme.spacing.sm} ${theme.spacing.md}`,
                borderRadius: theme.radii.md,
                border: `1px solid ${isSelected ? theme.colors.borderStrong : theme.colors.border}`,
                background: isSelected ? theme.colors.primarySoft : theme.colors.surfaceAlt,
                cursor: 'pointer',
              }}
            >
              <input
                type="radio"
                name="profile"
                value={option.value}
                checked={isSelected}
                onChange={() => updateForm('profile', option.value)}
                style={{ accentColor: theme.colors.primary }}
              />
              <div style={{ display: 'grid', gap: '0.15rem' }}>
                <span style={{ fontWeight: isSelected ? theme.typography.fontWeightBold : theme.typography.fontWeightMedium }}>
                  {option.label}
                  {isRecommended ? ' • Default' : ''}
                </span>
                <span style={{ color: theme.colors.textMuted, fontSize: theme.typography.fontSizeSm }}>
                  {option.description}
                </span>
              </div>
            </label>
          );
        })}
      </div>
      {error ? (
        <p style={{ margin: 0, color: theme.colors.danger, fontWeight: theme.typography.fontWeightMedium }}>{error}</p>
      ) : null}
    </div>
  );
}

function ProjectStorageStep({ error }: { error?: string }): JSX.Element {
  const { formData, updateForm } = useWizardForm();
  const theme = useTheme();

  return (
    <div style={{ display: 'grid', gap: theme.spacing.md }}>
      <div style={{ display: 'grid', gap: theme.spacing.xs }}>
        <h3 style={{ margin: 0 }}>Project root and cache</h3>
        <p style={{ margin: 0, color: theme.colors.textMuted }}>
          Point OnePiece Studio Desktop at your primary project root and where you want cached assets to live.
        </p>
      </div>
      <div style={{ display: 'grid', gap: theme.spacing.sm }}>
        <TextInput
          label="Project root *"
          placeholder="/path/to/projects"
          value={formData.projectRoot}
          onChange={(event) => updateForm('projectRoot', event.target.value)}
          errorText={error}
        />
        <TextInput
          label="Cache location"
          placeholder="/path/to/cache"
          value={formData.cacheLocation}
          onChange={(event) => updateForm('cacheLocation', event.target.value)}
        />
        <TextInput
          label="Python path"
          placeholder="/usr/bin/python3"
          value={formData.pythonPath}
          onChange={(event) => updateForm('pythonPath', event.target.value)}
        />
      </div>
    </div>
  );
}

function IntegrationsStep(): JSX.Element {
  const { formData, updateNested } = useWizardForm();
  const theme = useTheme();

  return (
    <div style={{ display: 'grid', gap: theme.spacing.md }}>
      <div style={{ display: 'grid', gap: theme.spacing.xs }}>
        <h3 style={{ margin: 0 }}>Integrations (optional)</h3>
        <p style={{ margin: 0, color: theme.colors.textMuted }}>
          Provide ShotGrid and AWS credentials now or skip for later configuration.
        </p>
      </div>
      <div
        style={{
          display: 'grid',
          gap: theme.spacing.md,
          gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))',
        }}
      >
        <div style={{ display: 'grid', gap: theme.spacing.sm }}>
          <h4 style={{ margin: 0 }}>ShotGrid</h4>
          <TextInput
            label="Site URL"
            placeholder="https://your-site.shotgrid.autodesk.com"
            value={formData.shotgrid.url || ''}
            onChange={(event) => updateNested('shotgrid', 'url', event.target.value)}
          />
          <TextInput
            label="Script name"
            placeholder="api-script"
            value={formData.shotgrid.scriptName || ''}
            onChange={(event) => updateNested('shotgrid', 'scriptName', event.target.value)}
          />
          <TextInput
            label="API key"
            placeholder="********"
            type="password"
            value={formData.shotgrid.apiKey || ''}
            onChange={(event) => updateNested('shotgrid', 'apiKey', event.target.value)}
          />
        </div>
        <div style={{ display: 'grid', gap: theme.spacing.sm }}>
          <h4 style={{ margin: 0 }}>AWS (optional)</h4>
          <TextInput
            label="Access key ID"
            placeholder="AKIA..."
            value={formData.aws.accessKeyId || ''}
            onChange={(event) => updateNested('aws', 'accessKeyId', event.target.value)}
          />
          <TextInput
            label="Secret access key"
            placeholder="********"
            type="password"
            value={formData.aws.secretAccessKey || ''}
            onChange={(event) => updateNested('aws', 'secretAccessKey', event.target.value)}
          />
          <TextInput
            label="Region"
            placeholder="us-west-2"
            value={formData.aws.region || ''}
            onChange={(event) => updateNested('aws', 'region', event.target.value)}
          />
          <TextInput
            label="Default bucket"
            placeholder="studio-bucket"
            value={formData.aws.defaultBucket || ''}
            onChange={(event) => updateNested('aws', 'defaultBucket', event.target.value)}
            helpText="Skip for now if you prefer to wire these later."
          />
        </div>
      </div>
    </div>
  );
}

function DccSelectionStep(): JSX.Element {
  const { formData, updateDcc } = useWizardForm();
  const theme = useTheme();
  const dccOptions: { key: DccAppKey; label: string; placeholder: string }[] = [
    { key: 'maya', label: 'Maya', placeholder: '/usr/autodesk/maya2024/bin/maya' },
    { key: 'blender', label: 'Blender', placeholder: '/Applications/Blender.app/Contents/MacOS/Blender' },
    { key: 'unreal', label: 'Unreal', placeholder: '/path/to/UnrealEditor' },
  ];

  return (
    <div style={{ display: 'grid', gap: theme.spacing.md }}>
      <div style={{ display: 'grid', gap: theme.spacing.xs }}>
        <h3 style={{ margin: 0 }}>Select your DCCs</h3>
        <p style={{ margin: 0, color: theme.colors.textMuted }}>
          Choose which DCCs to surface in the desktop app and include paths when custom installs are required.
        </p>
      </div>
      <div
        style={{
          display: 'grid',
          gap: theme.spacing.md,
          gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))',
        }}
      >
        {dccOptions.map((option) => (
          <div
            key={option.key}
            style={{
              display: 'grid',
              gap: theme.spacing.sm,
              padding: theme.spacing.sm,
              borderRadius: theme.radii.md,
              border: `1px solid ${theme.colors.border}`,
              background: theme.colors.surfaceAlt,
            }}
          >
            <label style={{ display: 'flex', alignItems: 'center', gap: theme.spacing.sm }}>
              <input
                type="checkbox"
                checked={formData.dcc[option.key].enabled}
                onChange={(event) => updateDcc(option.key, { enabled: event.target.checked })}
                style={{ accentColor: theme.colors.primary }}
              />
              <span style={{ fontWeight: theme.typography.fontWeightMedium }}>{option.label}</span>
            </label>
            <TextInput
              label="Executable path"
              placeholder={option.placeholder}
              value={formData.dcc[option.key].executablePath || ''}
              onChange={(event) => updateDcc(option.key, { executablePath: event.target.value })}
              disabled={!formData.dcc[option.key].enabled}
              helpText="Provide only if a custom install path is needed."
            />
          </div>
        ))}
      </div>
    </div>
  );
}

function SummaryStep({
  onBack,
  onFinish,
  isSubmitting,
  canFinish,
  error,
}: {
  onBack: () => void;
  onFinish: (options?: { openEnvironmentReport?: boolean }) => void;
  isSubmitting: boolean;
  canFinish: boolean;
  error?: string;
}): JSX.Element {
  const { formData } = useWizardForm();
  const theme = useTheme();

  return (
    <div style={{ display: 'grid', gap: theme.spacing.md }}>
      <div style={{ display: 'grid', gap: theme.spacing.xs }}>
        <h3 style={{ margin: 0 }}>Review your setup</h3>
        <p style={{ margin: 0, color: theme.colors.textMuted }}>
          Confirm these details before we save your configuration.
        </p>
      </div>
      <div
        style={{
          display: 'grid',
          gap: theme.spacing.sm,
          gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
          background: theme.colors.surfaceAlt,
          padding: theme.spacing.sm,
          borderRadius: theme.radii.md,
          border: `1px solid ${theme.colors.border}`,
        }}
      >
        <div>
          <h4 style={{ margin: '0 0 0.25rem' }}>Profile</h4>
          <p style={{ margin: 0 }}>{formData.profile || 'Not selected'}</p>
        </div>
        <div>
          <h4 style={{ margin: '0 0 0.25rem' }}>Project root</h4>
          <p style={{ margin: 0 }}>{formData.projectRoot || 'Not provided'}</p>
        </div>
        <div>
          <h4 style={{ margin: '0 0 0.25rem' }}>Cache location</h4>
          <p style={{ margin: 0 }}>{formData.cacheLocation || 'Not provided'}</p>
        </div>
        <div>
          <h4 style={{ margin: '0 0 0.25rem' }}>Python path</h4>
          <p style={{ margin: 0 }}>{formData.pythonPath || 'Not provided'}</p>
        </div>
        <div>
          <h4 style={{ margin: '0 0 0.25rem' }}>ShotGrid</h4>
          <p style={{ margin: 0 }}>{formData.shotgrid.url || 'Not provided'}</p>
          <p style={{ margin: 0 }}>{formData.shotgrid.scriptName || ''}</p>
        </div>
        <div>
          <h4 style={{ margin: '0 0 0.25rem' }}>AWS</h4>
          <p style={{ margin: 0 }}>{formData.aws.accessKeyId || 'No access key'}</p>
          <p style={{ margin: 0 }}>{formData.aws.region || ''}</p>
          <p style={{ margin: 0 }}>{formData.aws.defaultBucket || ''}</p>
        </div>
        <div>
          <h4 style={{ margin: '0 0 0.25rem' }}>DCCs</h4>
          {(['maya', 'blender', 'unreal'] as DccAppKey[]).map((key) => (
            <p key={key} style={{ margin: 0 }}>
              {key}: {formData.dcc[key].enabled ? 'Enabled' : 'Skipped'}
              {formData.dcc[key].executablePath ? ` (${formData.dcc[key].executablePath})` : ''}
            </p>
          ))}
        </div>
      </div>
      {error ? (
        <p style={{ margin: 0, color: theme.colors.danger, fontWeight: theme.typography.fontWeightMedium }}>{error}</p>
      ) : null}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          gap: theme.spacing.sm,
          flexWrap: 'wrap',
        }}
      >
        <Button
          variant="ghost"
          onClick={() => onFinish({ openEnvironmentReport: true })}
          disabled={isSubmitting}
        >
          View environment report
        </Button>
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: theme.spacing.sm }}>
          <Button variant="secondary" onClick={onBack} disabled={isSubmitting}>
            Back
          </Button>
          <Button
            variant="primary"
            onClick={() => onFinish()}
            isLoading={isSubmitting}
            disabled={!canFinish}
          >
            Finish setup
          </Button>
        </div>
      </div>
    </div>
  );
}

function FirstRunWizardContent({ onComplete }: FirstRunWizardProps): JSX.Element {
  const [currentStep, setCurrentStep] = useState(0);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [isSubmitting, setIsSubmitting] = useState(false);
  const { formData, detectionWarning } = useWizardForm();
  const theme = useTheme();

  const canFinish = useMemo(
    () => Boolean(formData.profile) && Boolean(formData.projectRoot.trim()),
    [formData.profile, formData.projectRoot],
  );

  const stepIsValid = useMemo(() => {
    if (currentStep === 1) {
      return Boolean(formData.profile);
    }

    if (currentStep === 2) {
      return Boolean(formData.projectRoot.trim());
    }

    if (currentStep === 5) {
      return canFinish;
    }

    return true;
  }, [canFinish, currentStep, formData.profile, formData.projectRoot]);

  const validateStep = (stepIndex: number): boolean => {
    const nextErrors: Record<string, string> = {};
    if ((stepIndex === 1 || stepIndex === 5) && !formData.profile) {
      nextErrors.profile = 'Select a profile to continue.';
    }
    if ((stepIndex === 2 || stepIndex === 5) && !formData.projectRoot.trim()) {
      nextErrors.projectRoot = 'Project root is required.';
    }

    setErrors(nextErrors);
    return Object.keys(nextErrors).length === 0;
  };

  const goNext = (): void => {
    if (!validateStep(currentStep)) {
      return;
    }
    setCurrentStep((prev) => prev + 1);
  };

  const goBack = (): void => {
    setErrors({});
    setCurrentStep((prev) => Math.max(0, prev - 1));
  };

  const handleFinish = async (options?: { openEnvironmentReport?: boolean }): Promise<void> => {
    if (!validateStep(5)) {
      return;
    }

    setIsSubmitting(true);
    setErrors({});

    const payload: Partial<DesktopConfig> = {
      profile: formData.profile || undefined,
      projectRoot: formData.projectRoot || undefined,
      cacheLocation: formData.cacheLocation || undefined,
      pythonPath: formData.pythonPath || undefined,
      shotgrid:
        formData.shotgrid.url || formData.shotgrid.scriptName || formData.shotgrid.apiKey
          ? {
              url: formData.shotgrid.url || undefined,
              scriptName: formData.shotgrid.scriptName || undefined,
              apiKey: formData.shotgrid.apiKey || undefined,
            }
          : undefined,
      aws:
        formData.aws.accessKeyId || formData.aws.secretAccessKey || formData.aws.region || formData.aws.defaultBucket
          ? {
              accessKeyId: formData.aws.accessKeyId || undefined,
              secretAccessKey: formData.aws.secretAccessKey || undefined,
              region: formData.aws.region || undefined,
              defaultBucket: formData.aws.defaultBucket || undefined,
            }
          : undefined,
      dcc: formData.dcc,
    };

    try {
      await window.electron.invoke('config/save', { ...payload, hasCompletedWizard: true });
      await window.electron.invoke('config/get');

      // Run a quick doctor check to surface obvious environment issues. This mirrors the diagnostics
      // screen experience but keeps the UX inline with the wizard. Non-blocking: we still continue
      // onboarding even if the doctor fails so users can recover later.
      try {
        await window.electron.invoke('python/run-doctor');
      } catch (doctorError) {
        console.warn('onepiece doctor did not complete during setup', doctorError);
      }

      onComplete(options);
    } catch (error) {
      setErrors({ submit: 'Failed to save configuration. Please try again.' });
      console.error('Error saving configuration', error);
    } finally {
      setIsSubmitting(false);
    }
  };

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent): void => {
      if (event.key === 'Enter') {
        if (currentStep === 5 && canFinish && !isSubmitting) {
          event.preventDefault();
          void handleFinish();
          return;
        }

        if (currentStep >= 0 && currentStep < 5 && stepIsValid && !isSubmitting) {
          event.preventDefault();
          goNext();
        }
      }

      if (event.key === 'Escape') {
        if (currentStep > 0 && !isSubmitting) {
          event.preventDefault();
          goBack();
        }
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [canFinish, currentStep, goBack, goNext, handleFinish, isSubmitting, stepIsValid]);

  return (
    <div
      style={{
        minHeight: '100vh',
        background: roleColors.background,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: designTokens.spacing.xl,
        boxSizing: 'border-box',
      }}
    >
      <Card
        style={{
          width: '100%',
          maxWidth: '800px',
          display: 'grid',
          gap: theme.spacing.lg,
          padding: designTokens.spacing.xl,
        }}
      >
        <SectionHeader
          title="First-time setup"
          subtitle="Follow the guided steps to configure your environment, storage, and integrations."
        />
        {detectionWarning ? (
          <div
            role="alert"
            style={{
              background: hexToRgba(theme.colors.warning, 0.12),
              border: `1px solid ${hexToRgba(theme.colors.warning, 0.6)}`,
              borderRadius: theme.radii.md,
              padding: `${theme.spacing.sm} ${theme.spacing.md}`,
              color: theme.colors.text,
              display: 'flex',
              gap: theme.spacing.sm,
              alignItems: 'center',
            }}
          >
            <span style={{ fontWeight: theme.typography.fontWeightBold }}>Environment detection</span>
            <span style={{ color: theme.colors.text }}>{detectionWarning}</span>
          </div>
        ) : null}
        <StepIndicator currentStep={currentStep} />
        <WizardStep stepKey={currentStep}>
          <div style={{ display: 'grid', gap: theme.spacing.lg }}>
            {currentStep === 0 && <WelcomeStep onNext={goNext} />}
            {currentStep === 1 && <UsageProfileStep error={errors.profile} />}
            {currentStep === 2 && <ProjectStorageStep error={errors.projectRoot} />}
            {currentStep === 3 && <IntegrationsStep />}
            {currentStep === 4 && <DccSelectionStep />}
            {currentStep === 5 && (
              <SummaryStep
                onBack={goBack}
                onFinish={handleFinish}
                isSubmitting={isSubmitting}
                canFinish={canFinish}
                error={errors.submit}
              />
            )}
            {currentStep > 0 && currentStep < 5 ? (
              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: theme.spacing.sm }}>
                <Button variant="secondary" onClick={goBack} disabled={isSubmitting}>
                  Back
                </Button>
                <Button variant="primary" onClick={goNext} disabled={isSubmitting || !stepIsValid}>
                  Continue
                </Button>
              </div>
            ) : null}
          </div>
        </WizardStep>
      </Card>
    </div>
  );
}

export function FirstRunWizard({ onComplete }: FirstRunWizardProps): JSX.Element {
  return (
    <WizardFormProvider>
      <FirstRunWizardContent onComplete={onComplete} />
    </WizardFormProvider>
  );
}

export default FirstRunWizard;
