import React, { useMemo, useState } from 'react';
import { Button, Card, SectionHeader, TextInput, useToast } from '../ui';
import { useTheme } from '../../styles/ThemeContext';
import { normalizeCostInsights, type CostInsightsResponse } from '../../utils/perona';

const DEFAULT_HOST = '127.0.0.1';
const DEFAULT_PORT = '8065';

type ProjectSelection = { name: string; path: string };

type PeronaPanelProps = {
  project?: ProjectSelection | null;
};

function PeronaPanel({ project }: PeronaPanelProps): JSX.Element {
  const theme = useTheme();
  const { showToast } = useToast();

  const [host, setHost] = useState(DEFAULT_HOST);
  const [port, setPort] = useState(DEFAULT_PORT);
  const [reload, setReload] = useState(false);
  const [logLevel, setLogLevel] = useState('info');
  const [isStartingDashboard, setIsStartingDashboard] = useState(false);
  const [dashboardStarted, setDashboardStarted] = useState(false);
  const [dashboardError, setDashboardError] = useState<string | null>(null);

  const [insights, setInsights] = useState<string[]>([]);
  const [insightsLoading, setInsightsLoading] = useState(false);
  const [insightsError, setInsightsError] = useState<string | null>(null);
  const [lastFetchedAt, setLastFetchedAt] = useState<string | null>(null);

  const dashboardUrl = useMemo(() => {
    const normalizedHost = host.trim() || DEFAULT_HOST;
    const portNumber = Number.parseInt(port, 10);
    const normalizedPort = Number.isFinite(portNumber) ? portNumber : Number(DEFAULT_PORT);
    return `http://${normalizedHost}:${normalizedPort}`;
  }, [host, port]);

  const handleStartDashboard = async (): Promise<void> => {
    const normalizedHost = host.trim() || DEFAULT_HOST;
    const portNumber = Number.parseInt(port, 10);
    const normalizedPort = Number.isFinite(portNumber) ? portNumber : Number(DEFAULT_PORT);
    const normalizedLogLevel = logLevel.trim() || undefined;

    setIsStartingDashboard(true);
    setDashboardError(null);
    try {
      await window.electron.invoke('perona/web-dashboard', {
        host: normalizedHost,
        port: normalizedPort,
        reload,
        logLevel: normalizedLogLevel,
      });
      setDashboardStarted(true);
      showToast({
        title: 'Perona dashboard starting',
        description: `Serving at ${dashboardUrl}`,
        variant: 'success',
      });
    } catch (error) {
      console.error('Failed to start Perona dashboard', error);
      setDashboardError('Unable to start Perona dashboard.');
      showToast({
        title: 'Dashboard failed to start',
        description: 'Check your Python environment and try again.',
        variant: 'error',
      });
    } finally {
      setIsStartingDashboard(false);
    }
  };

  const handleOpenDashboard = async (): Promise<void> => {
    try {
      await window.electron.invoke('open-url', { url: dashboardUrl });
    } catch (error) {
      console.error('Failed to open Perona dashboard in browser', error);
    }
  };

  const handleFetchInsights = async (): Promise<void> => {
    setInsightsLoading(true);
    setInsightsError(null);
    try {
      const response = await window.electron.invoke<CostInsightsResponse>('perona/cost-insights', {
        project: project?.path,
      });

      const normalized = normalizeCostInsights(response);
      setInsights(normalized);
      setLastFetchedAt(new Date().toISOString());

      if (normalized.length === 0) {
        setInsightsError('No insights available yet.');
      }
    } catch (error) {
      console.error('Failed to fetch Perona cost insights', error);
      setInsights([]);
      setInsightsError('Unable to fetch cost insights.');
    } finally {
      setInsightsLoading(false);
    }
  };

  return (
    <Card>
      <div style={{ display: 'grid', gap: theme.spacing.lg }}>
        <div style={{ display: 'grid', gap: theme.spacing.sm }}>
          <SectionHeader
            title="Dashboard server"
            subtitle="Launch the Perona dashboard locally as a background service."
            action={
              <div style={{ display: 'flex', gap: theme.spacing.sm, alignItems: 'center' }}>
                <Button onClick={() => void handleStartDashboard()} isLoading={isStartingDashboard}>
                  {dashboardStarted ? 'Restart dashboard' : 'Start Perona dashboard'}
                </Button>
                {dashboardStarted ? (
                  <Button variant="secondary" onClick={() => void handleOpenDashboard()}>
                    Open dashboard in browser
                  </Button>
                ) : null}
              </div>
            }
          />

          <div
            style={{
              display: 'grid',
              gap: theme.spacing.sm,
              gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
            }}
          >
            <TextInput label="Host" value={host} onChange={(event) => setHost(event.target.value)} />
            <TextInput
              label="Port"
              value={port}
              inputMode="numeric"
              onChange={(event) => setPort(event.target.value)}
            />
            <TextInput
              label="Log level"
              value={logLevel}
              onChange={(event) => setLogLevel(event.target.value)}
              helpText="Optional log verbosity (e.g. info, debug)."
            />
          </div>

          <label style={{ display: 'flex', alignItems: 'center', gap: theme.spacing.xs }}>
            <input
              type="checkbox"
              checked={reload}
              onChange={(event) => setReload(event.target.checked)}
              style={{ width: '1rem', height: '1rem' }}
            />
            <span style={{ color: theme.colors.text }}>Enable reload mode</span>
          </label>

          <p style={{ margin: 0, color: theme.colors.textMuted }}>
            {`The dashboard will start on ${dashboardUrl}. Keep this window open to maintain the service.`}
          </p>
          {dashboardError ? <p style={{ color: theme.colors.danger }}>{dashboardError}</p> : null}
        </div>

        <div style={{ display: 'grid', gap: theme.spacing.sm }}>
          <SectionHeader
            title="Cost insights"
            subtitle="Run Perona cost insights to review recommendations for your project."
            action={
              <Button variant="secondary" isLoading={insightsLoading} onClick={() => void handleFetchInsights()}>
                Fetch cost insights
              </Button>
            }
          />
          {project?.name ? (
            <p style={{ margin: 0, color: theme.colors.textMuted }}>
              Using project: <strong>{project.name}</strong>
            </p>
          ) : null}
          {insightsError ? <p style={{ color: theme.colors.warning }}>{insightsError}</p> : null}
          {insights.length > 0 ? (
            <ul style={{ margin: 0, paddingLeft: '1.1rem', display: 'grid', gap: theme.spacing.xs }}>
              {insights.map((insight, index) => (
                <li key={`${insight}-${index}`}>{insight}</li>
              ))}
            </ul>
          ) : (
            <p style={{ margin: 0, color: theme.colors.textMuted }}>Run cost insights to see recommendations.</p>
          )}
          {lastFetchedAt ? (
            <p style={{ margin: 0, color: theme.colors.textMuted }}>
              Last fetched {new Date(lastFetchedAt).toLocaleString()}
            </p>
          ) : null}
        </div>
      </div>
    </Card>
  );
}

export default PeronaPanel;
