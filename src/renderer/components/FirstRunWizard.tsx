import React, { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';

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
  onComplete: () => void;
};

const defaultFormState: WizardFormState = {
  profile: '',
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

declare global {
  interface Window {
    electron: {
      invoke: <T = unknown>(channel: string, payload?: unknown) => Promise<T>;
    };
  }
}

type DetectedEnv = {
  pythonPathGuess?: string;
  dccs: Partial<Record<DccAppKey, string>>;
};

function WizardFormProvider({ children }: { children: ReactNode }): JSX.Element {
  const [formData, setFormData] = useState<WizardFormState>(defaultFormState);

  useEffect(() => {
    let isMounted = true;

    const detectEnv = async (): Promise<void> => {
      try {
        const env = await window.electron.invoke<DetectedEnv>('system/detect-env');

        if (!isMounted || !env) {
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
      }
    };

    void detectEnv();

    return () => {
      isMounted = false;
    };
  }, []);

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

  const value = useMemo(() => ({ formData, updateForm, updateNested, updateDcc }), [formData]);

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

function Stepper({ currentStep }: { currentStep: number }): JSX.Element {
  return (
    <ol className="op-stepper">
      {steps.map((label, index) => {
        const isActive = index === currentStep;
        const isComplete = index < currentStep;
        return (
          <li key={label} className={`op-step ${isActive ? 'active' : ''} ${isComplete ? 'complete' : ''}`}>
            <span className="op-step-index">{index + 1}</span>
            <span className="op-step-label">{label}</span>
          </li>
        );
      })}
    </ol>
  );
}

function WelcomeStep({ onNext }: { onNext: () => void }): JSX.Element {
  return (
    <div className="op-card">
      <h2>Welcome to OnePiece Studio Desktop</h2>
      <p>
        This guided setup will capture your workflow preferences, project storage locations, and optional integrations so we can
        configure the desktop experience for your studio.
      </p>
      <button type="button" onClick={onNext} className="op-primary">
        Get started
      </button>
    </div>
  );
}

function UsageProfileStep({ error }: { error?: string }): JSX.Element {
  const { formData, updateForm } = useWizardForm();
  const options: { label: string; value: ProfileOption }[] = [
    { label: 'Small VFX studio', value: 'vfx' },
    { label: 'Arch-viz studio', value: 'archviz' },
    { label: 'Solo artist / freelancer', value: 'freelancer' },
    { label: 'Just trying the demo stack', value: 'demo' },
  ];

  return (
    <div className="op-card">
      <h3>Tell us about your usage</h3>
      <p>Choose the description that best fits your typical workload.</p>
      <div className="op-radio-group">
        {options.map((option) => (
          <label key={option.value} className="op-radio">
            <input
              type="radio"
              name="profile"
              value={option.value}
              checked={formData.profile === option.value}
              onChange={() => updateForm('profile', option.value)}
            />
            <span>{option.label}</span>
          </label>
        ))}
      </div>
      {error ? <p className="op-error">{error}</p> : null}
    </div>
  );
}

function ProjectStorageStep({ error }: { error?: string }): JSX.Element {
  const { formData, updateForm } = useWizardForm();

  return (
    <div className="op-card">
      <h3>Project root and cache</h3>
      <p>Point OnePiece Studio Desktop at your primary project root and where you want cached assets to live.</p>
      <label className="op-field">
        <span>Project root *</span>
        <input
          type="text"
          placeholder="/path/to/projects"
          value={formData.projectRoot}
          onChange={(event) => updateForm('projectRoot', event.target.value)}
        />
      </label>
      <label className="op-field">
        <span>Cache location</span>
        <input
          type="text"
          placeholder="/path/to/cache"
          value={formData.cacheLocation}
          onChange={(event) => updateForm('cacheLocation', event.target.value)}
        />
      </label>
      <label className="op-field">
        <span>Python path</span>
        <input
          type="text"
          placeholder="/usr/bin/python3"
          value={formData.pythonPath}
          onChange={(event) => updateForm('pythonPath', event.target.value)}
        />
      </label>
      {error ? <p className="op-error">{error}</p> : null}
    </div>
  );
}

function IntegrationsStep(): JSX.Element {
  const { formData, updateNested } = useWizardForm();

  return (
    <div className="op-card">
      <h3>Integrations (optional)</h3>
      <p>Provide ShotGrid and AWS credentials now or skip for later configuration.</p>
      <div className="op-grid">
        <div>
          <h4>ShotGrid</h4>
          <label className="op-field">
            <span>Site URL</span>
            <input
              type="text"
              placeholder="https://your-site.shotgrid.autodesk.com"
              value={formData.shotgrid.url || ''}
              onChange={(event) => updateNested('shotgrid', 'url', event.target.value)}
            />
          </label>
          <label className="op-field">
            <span>Script name</span>
            <input
              type="text"
              placeholder="api-script"
              value={formData.shotgrid.scriptName || ''}
              onChange={(event) => updateNested('shotgrid', 'scriptName', event.target.value)}
            />
          </label>
          <label className="op-field">
            <span>API key</span>
            <input
              type="password"
              placeholder="********"
              value={formData.shotgrid.apiKey || ''}
              onChange={(event) => updateNested('shotgrid', 'apiKey', event.target.value)}
            />
          </label>
        </div>
        <div>
          <h4>AWS (optional)</h4>
          <label className="op-field">
            <span>Access key ID</span>
            <input
              type="text"
              placeholder="AKIA..."
              value={formData.aws.accessKeyId || ''}
              onChange={(event) => updateNested('aws', 'accessKeyId', event.target.value)}
            />
          </label>
          <label className="op-field">
            <span>Secret access key</span>
            <input
              type="password"
              placeholder="********"
              value={formData.aws.secretAccessKey || ''}
              onChange={(event) => updateNested('aws', 'secretAccessKey', event.target.value)}
            />
          </label>
          <label className="op-field">
            <span>Region</span>
            <input
              type="text"
              placeholder="us-west-2"
              value={formData.aws.region || ''}
              onChange={(event) => updateNested('aws', 'region', event.target.value)}
            />
          </label>
          <label className="op-field">
            <span>Default bucket</span>
            <input
              type="text"
              placeholder="studio-bucket"
              value={formData.aws.defaultBucket || ''}
              onChange={(event) => updateNested('aws', 'defaultBucket', event.target.value)}
            />
          </label>
          <p className="op-note">Skip for now if you prefer to wire these later.</p>
        </div>
      </div>
    </div>
  );
}

function DccSelectionStep(): JSX.Element {
  const { formData, updateDcc } = useWizardForm();
  const dccOptions: { key: DccAppKey; label: string; placeholder: string }[] = [
    { key: 'maya', label: 'Maya', placeholder: '/usr/autodesk/maya2024/bin/maya' },
    { key: 'blender', label: 'Blender', placeholder: '/Applications/Blender.app/Contents/MacOS/Blender' },
    { key: 'unreal', label: 'Unreal', placeholder: '/path/to/UnrealEditor' },
  ];

  return (
    <div className="op-card">
      <h3>Select your DCCs</h3>
      <p>Choose which DCCs to surface in the desktop app and include paths when custom installs are required.</p>
      <div className="op-grid">
        {dccOptions.map((option) => (
          <div key={option.key} className="op-dcc">
            <label className="op-checkbox">
              <input
                type="checkbox"
                checked={formData.dcc[option.key].enabled}
                onChange={(event) => updateDcc(option.key, { enabled: event.target.checked })}
              />
              <span>{option.label}</span>
            </label>
            <label className="op-field">
              <span>Executable path</span>
              <input
                type="text"
                placeholder={option.placeholder}
                value={formData.dcc[option.key].executablePath || ''}
                onChange={(event) => updateDcc(option.key, { executablePath: event.target.value })}
                disabled={!formData.dcc[option.key].enabled}
              />
            </label>
          </div>
        ))}
      </div>
    </div>
  );
}

function SummaryStep({ onBack, onFinish, isSubmitting, error }: { onBack: () => void; onFinish: () => void; isSubmitting: boolean; error?: string; }): JSX.Element {
  const { formData } = useWizardForm();
  return (
    <div className="op-card">
      <h3>Review your setup</h3>
      <p>Confirm these details before we save your configuration.</p>
      <div className="op-summary">
        <div>
          <h4>Profile</h4>
          <p>{formData.profile || 'Not selected'}</p>
        </div>
        <div>
          <h4>Project root</h4>
          <p>{formData.projectRoot || 'Not provided'}</p>
        </div>
        <div>
          <h4>Cache location</h4>
          <p>{formData.cacheLocation || 'Not provided'}</p>
        </div>
        <div>
          <h4>Python path</h4>
          <p>{formData.pythonPath || 'Not provided'}</p>
        </div>
        <div>
          <h4>ShotGrid</h4>
          <p>{formData.shotgrid.url || 'Not provided'}</p>
          <p>{formData.shotgrid.scriptName || ''}</p>
        </div>
        <div>
          <h4>AWS</h4>
          <p>{formData.aws.accessKeyId || 'No access key'}</p>
          <p>{formData.aws.region || ''}</p>
          <p>{formData.aws.defaultBucket || ''}</p>
        </div>
        <div>
          <h4>DCCs</h4>
          {(['maya', 'blender', 'unreal'] as DccAppKey[]).map((key) => (
            <p key={key}>
              {key}: {formData.dcc[key].enabled ? 'Enabled' : 'Skipped'}
              {formData.dcc[key].executablePath ? ` (${formData.dcc[key].executablePath})` : ''}
            </p>
          ))}
        </div>
      </div>
      {error ? <p className="op-error">{error}</p> : null}
      <div className="op-actions">
        <button type="button" onClick={onBack} className="op-secondary" disabled={isSubmitting}>
          Back
        </button>
        <button type="button" onClick={onFinish} className="op-primary" disabled={isSubmitting}>
          {isSubmitting ? 'Saving...' : 'Finish setup'}
        </button>
      </div>
    </div>
  );
}

function FirstRunWizardContent({ onComplete }: FirstRunWizardProps): JSX.Element {
  const [currentStep, setCurrentStep] = useState(0);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [isSubmitting, setIsSubmitting] = useState(false);
  const { formData } = useWizardForm();

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

  const handleFinish = async (): Promise<void> => {
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
      onComplete();
    } catch (error) {
      setErrors({ submit: 'Failed to save configuration. Please try again.' });
      console.error('Error saving configuration', error);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="op-wizard">
      <Stepper currentStep={currentStep} />
      {currentStep === 0 && <WelcomeStep onNext={goNext} />}
      {currentStep === 1 && <UsageProfileStep error={errors.profile} />}
      {currentStep === 2 && <ProjectStorageStep error={errors.projectRoot} />}
      {currentStep === 3 && <IntegrationsStep />}
      {currentStep === 4 && <DccSelectionStep />}
      {currentStep === 5 && (
        <SummaryStep onBack={goBack} onFinish={handleFinish} isSubmitting={isSubmitting} error={errors.submit} />
      )}
      {currentStep > 0 && currentStep < 5 ? (
        <div className="op-actions">
          <button type="button" onClick={goBack} className="op-secondary">
            Back
          </button>
          <button type="button" onClick={goNext} className="op-primary">
            Continue
          </button>
        </div>
      ) : null}
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
