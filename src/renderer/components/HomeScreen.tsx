import React, { useEffect, useMemo, useState } from 'react';

interface DesktopConfig {
  hasCompletedWizard: boolean;
  createdAt: string;
  updatedAt: string;
  profile?: 'vfx' | 'archviz' | 'freelancer' | 'demo';
  pythonPath?: string;
  projectRoot?: string;
}

type HomeScreenProps = {
  config?: DesktopConfig;
};

interface ServiceSummary {
  id: string;
  name: string;
  pid: number;
}

type ServiceKey = 'trafalgar' | 'perona' | 'uta' | 'tester';

interface ServiceDefinition {
  key: ServiceKey;
  name: string;
  description: string;
  args: string[];
}

interface HealthCheckState {
  running: boolean;
  exitCode: number | null;
  stdout: string;
  stderr: string;
  error?: string;
}

declare global {
  interface Window {
    electron: {
      invoke: <T = unknown>(channel: string, payload?: unknown) => Promise<T>;
    };
  }
}

const SERVICE_DEFINITIONS: ServiceDefinition[] = [
  {
    key: 'trafalgar',
    name: 'Trafalgar',
    description: 'Asset management and pipeline orchestration.',
    args: ['-m', 'apps.trafalgar'],
  },
  {
    key: 'perona',
    name: 'Perona',
    description: 'Perona dashboard web service.',
    args: ['-m', 'apps.perona'],
  },
  {
    key: 'uta',
    name: 'Uta Control Center',
    description: 'Monitoring and operations control center.',
    args: ['-m', 'apps.uta'],
  },
  {
    key: 'tester',
    name: 'Tester Demo Stack',
    description: 'Demo stack for validation and testing.',
    args: ['-m', 'apps.tester'],
  },
];

const UTA_PORT = 8080;

function HomeScreen({ config: initialConfig }: HomeScreenProps): JSX.Element {
  const [config, setConfig] = useState<DesktopConfig | null>(initialConfig ?? null);
  const [services, setServices] = useState<ServiceSummary[]>([]);
  const [serviceError, setServiceError] = useState<string | null>(null);
  const [healthCheck, setHealthCheck] = useState<HealthCheckState>({
    running: false,
    exitCode: null,
    stdout: '',
    stderr: '',
  });
  const [serviceActions, setServiceActions] = useState<Record<ServiceKey, 'starting' | 'stopping' | null>>(() =>
    SERVICE_DEFINITIONS.reduce(
      (acc, definition) => ({
        ...acc,
        [definition.key]: null,
      }),
      {} as Record<ServiceKey, 'starting' | 'stopping' | null>,
    ),
  );

  const fetchConfig = async (): Promise<void> => {
    try {
      const loadedConfig = await window.electron.invoke<DesktopConfig>('config/get');
      setConfig(loadedConfig);
    } catch (error) {
      console.error('Failed to load desktop config', error);
    }
  };

  const fetchServices = async (): Promise<void> => {
    try {
      const summaries = await window.electron.invoke<ServiceSummary[]>('python/list-services');
      setServices(summaries);
      setServiceError(null);
    } catch (error) {
      console.error('Failed to list services', error);
      setServiceError('Unable to retrieve service status.');
    }
  };

  useEffect(() => {
    if (!initialConfig) {
      void fetchConfig();
    }
    void fetchServices();

    const interval = setInterval(() => {
      void fetchServices();
    }, 5000);

    return () => clearInterval(interval);
  }, [initialConfig]);

  useEffect(() => {
    if (initialConfig) {
      setConfig(initialConfig);
    }
  }, [initialConfig]);

  const runningServicesByName = useMemo(() => {
    const map = new Map<string, ServiceSummary>();
    services.forEach((service) => {
      map.set(service.name, service);
    });
    return map;
  }, [services]);

  const handleStart = async (definition: ServiceDefinition): Promise<void> => {
    setServiceActions((prev) => ({ ...prev, [definition.key]: 'starting' }));
    try {
      await window.electron.invoke('python/start-service', {
        name: definition.name,
        args: definition.args,
      });
      await fetchServices();
    } catch (error) {
      console.error(`Failed to start ${definition.name}`, error);
      setServiceError(`Failed to start ${definition.name}.`);
    } finally {
      setServiceActions((prev) => ({ ...prev, [definition.key]: null }));
    }
  };

  const handleStop = async (definition: ServiceDefinition): Promise<void> => {
    const running = runningServicesByName.get(definition.name);
    if (!running) {
      setServiceError(`${definition.name} is not currently running.`);
      return;
    }

    setServiceActions((prev) => ({ ...prev, [definition.key]: 'stopping' }));
    try {
      await window.electron.invoke('python/stop-service', { id: running.id });
      await fetchServices();
    } catch (error) {
      console.error(`Failed to stop ${definition.name}`, error);
      setServiceError(`Failed to stop ${definition.name}.`);
    } finally {
      setServiceActions((prev) => ({ ...prev, [definition.key]: null }));
    }
  };

  const runHealthCheck = async (): Promise<void> => {
    setHealthCheck({ running: true, exitCode: null, stdout: '', stderr: '' });
    try {
      const result = await window.electron.invoke<{ code: number; stdout: string; stderr: string }>(
        'python/run-command',
        { args: ['-m', 'onepiece', 'doctor'] },
      );
      setHealthCheck({
        running: false,
        exitCode: result.code,
        stdout: result.stdout,
        stderr: result.stderr,
      });
    } catch (error) {
      console.error('Health check failed to execute', error);
      setHealthCheck({
        running: false,
        exitCode: null,
        stdout: '',
        stderr: '',
        error: 'Failed to run health check.',
      });
    }
  };

  const openUtaDashboard = (): void => {
    const url = `http://localhost:${UTA_PORT}`;
    void window.electron.invoke('open-url', { url });
  };

  const renderServiceStatus = (definition: ServiceDefinition): JSX.Element => {
    const running = runningServicesByName.get(definition.name);
    const isRunning = Boolean(running);
    const actionState = serviceActions[definition.key];

    return (
      <div key={definition.key} className="op-card op-service-card">
        <div className="op-service-header">
          <div>
            <h3>{definition.name}</h3>
            <p className="op-service-description">{definition.description}</p>
          </div>
          <span className={`op-status ${isRunning ? 'running' : 'stopped'}`}>
            {isRunning ? 'Running' : 'Stopped'}
          </span>
        </div>
        <div className="op-service-actions">
          <button
            type="button"
            className="op-primary"
            onClick={() => void handleStart(definition)}
            disabled={isRunning || actionState === 'starting'}
          >
            {actionState === 'starting' ? 'Starting…' : 'Start'}
          </button>
          <button
            type="button"
            className="op-secondary"
            onClick={() => void handleStop(definition)}
            disabled={!isRunning || actionState === 'stopping'}
          >
            {actionState === 'stopping' ? 'Stopping…' : 'Stop'}
          </button>
        </div>
        {isRunning && running?.pid ? <p className="op-service-meta">PID: {running.pid}</p> : null}
      </div>
    );
  };

  return (
    <div className="op-layout">
      <header className="op-header">
        <div>
          <p className="op-eyebrow">OnePiece Studio Desktop</p>
          <h1>Home</h1>
          <p>Manage your local services, run diagnostics, and open dashboards.</p>
        </div>
        <button type="button" className="op-primary" onClick={openUtaDashboard}>
          Open Uta Dashboard
        </button>
      </header>

      <section className="op-grid">
        <div className="op-card">
          <h2>Current configuration</h2>
          {config ? (
            <dl className="op-definition-list">
              <div>
                <dt>Profile</dt>
                <dd>{config.profile ?? 'Not set'}</dd>
              </div>
              <div>
                <dt>Project root</dt>
                <dd>{config.projectRoot ?? 'Not set'}</dd>
              </div>
              <div>
                <dt>Python path</dt>
                <dd>{config.pythonPath ?? 'Using system default'}</dd>
              </div>
            </dl>
          ) : (
            <p>Loading configuration…</p>
          )}
        </div>

        <div className="op-card">
          <div className="op-card-header">
            <h2>Health check</h2>
            <button type="button" className="op-primary" onClick={() => void runHealthCheck()} disabled={healthCheck.running}>
              {healthCheck.running ? 'Running…' : 'Run health check'}
            </button>
          </div>
          {healthCheck.exitCode !== null && !healthCheck.running ? (
            <div className={`op-badge ${healthCheck.exitCode === 0 ? 'success' : 'error'}`}>
              {healthCheck.exitCode === 0 ? 'Doctor check passed' : 'Doctor check reported issues'}
            </div>
          ) : null}
          {healthCheck.error ? <p className="op-error">{healthCheck.error}</p> : null}
          <div className="op-log-output">
            {healthCheck.stdout ? (
              <div>
                <h4>Stdout</h4>
                <pre>{healthCheck.stdout}</pre>
              </div>
            ) : null}
            {healthCheck.stderr ? (
              <div>
                <h4>Stderr</h4>
                <pre>{healthCheck.stderr}</pre>
              </div>
            ) : null}
            {!healthCheck.stdout && !healthCheck.stderr && !healthCheck.error ? (
              <p className="op-muted">Run the health check to see diagnostics.</p>
            ) : null}
          </div>
        </div>
      </section>

      <section>
        <div className="op-section-header">
          <div>
            <h2>Services</h2>
            <p>Start or stop the local stack components. Status is refreshed every 5 seconds.</p>
          </div>
          <button type="button" className="op-secondary" onClick={() => void fetchServices()}>
            Refresh status
          </button>
        </div>
        {serviceError ? <p className="op-error">{serviceError}</p> : null}
        <div className="op-service-grid">
          {SERVICE_DEFINITIONS.map((definition) => renderServiceStatus(definition))}
        </div>
      </section>
    </div>
  );
}

export default HomeScreen;
