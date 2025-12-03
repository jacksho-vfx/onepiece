import React, { useMemo, useState } from 'react';
import { Button, Card, SectionHeader, TextInput, useToast } from '../ui';
import { useTheme } from '../../styles/ThemeContext';
import {
  normalizeCostInsights,
  type CostInsightsResponse,
  type NormalizedCostInsight,
} from '../../utils/perona';

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
  const [settingsPath, setSettingsPath] = useState('');
  const [isStartingDashboard, setIsStartingDashboard] = useState(false);
  const [isStoppingDashboard, setIsStoppingDashboard] = useState(false);
  const [dashboardStarted, setDashboardStarted] = useState(false);
  const [dashboardServiceId, setDashboardServiceId] = useState<string | null>(null);
  const [dashboardError, setDashboardError] = useState<string | null>(null);

  const [insights, setInsights] = useState<NormalizedCostInsight[]>([]);
  const [rawInsights, setRawInsights] = useState<string | null>(null);
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
    const normalizedSettingsPath = settingsPath.trim() || undefined;

    setIsStartingDashboard(true);
    setDashboardError(null);
    try {
      const response = await window.electron.invoke<{ id?: string }>('perona/web-dashboard', {
        host: normalizedHost,
        port: normalizedPort,
        settingsPath: normalizedSettingsPath,
      });
      setDashboardServiceId(response?.id ?? null);
      setDashboardStarted(true);
      showToast({
        title: 'Perona dashboard starting',
        description: `Perona dashboard starting on ${dashboardUrl}`,
        variant: 'success',
      });
    } catch (error) {
      console.error('Failed to start Perona dashboard', error);
      setDashboardError('Unable to start Perona dashboard.');
      setDashboardServiceId(null);
      setDashboardStarted(false);
      showToast({
        title: 'Dashboard failed to start',
        description: 'Check your Python environment and try again.',
        variant: 'error',
      });
    } finally {
      setIsStartingDashboard(false);
    }
  };

  const handleStopDashboard = async (): Promise<void> => {
    if (!dashboardServiceId) {
      setDashboardStarted(false);
      return;
    }

    setIsStoppingDashboard(true);
    try {
      await window.electron.invoke('python/stop-service', { id: dashboardServiceId });
      setDashboardStarted(false);
      setDashboardServiceId(null);
      showToast({ title: 'Perona dashboard stopped', description: 'Background service stopped.', variant: 'success' });
    } catch (error) {
      console.error('Failed to stop Perona dashboard', error);
      showToast({
        title: 'Could not stop dashboard',
        description: 'Please check running services and try again.',
        variant: 'error',
      });
    } finally {
      setIsStoppingDashboard(false);
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
      setInsights(normalized.recommendations);
      setRawInsights(normalized.rawText);
      setLastFetchedAt(new Date().toISOString());

      if (normalized.recommendations.length === 0 && !normalized.rawText) {
        setInsightsError('No insights available yet.');
      }
    } catch (error) {
      console.error('Failed to fetch Perona cost insights', error);
      setInsights([]);
      setRawInsights(null);
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
                  Start Perona dashboard
                </Button>
                {dashboardStarted ? (
                  <Button
                    variant="secondary"
                    onClick={() => void handleStopDashboard()}
                    isLoading={isStoppingDashboard}
                  >
                    Stop dashboard
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
              label="Settings path"
              value={settingsPath}
              placeholder="Optional path to a settings file"
              onChange={(event) => setSettingsPath(event.target.value)}
            />
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: theme.spacing.sm, flexWrap: 'wrap' }}>
            <p style={{ margin: 0, color: theme.colors.textMuted }}>
              {`The dashboard will start on ${dashboardUrl}. Keep this window open to maintain the service.`}
            </p>
            {dashboardStarted ? (
              <Button variant="secondary" onClick={() => void handleOpenDashboard()}>
                Open in browser
              </Button>
            ) : null}
          </div>
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
            <div style={{ display: 'grid', gap: theme.spacing.sm }}>
              {insights.map((insight, index) => (
                <div
                  key={`${insight.title}-${index}`}
                  style={{
                    padding: `${theme.spacing.xs} ${theme.spacing.sm}`,
                    borderRadius: theme.radii.sm,
                    border: `1px solid ${theme.colors.border}`,
                    background: theme.colors.surface,
                  }}
                >
                  <p style={{ margin: 0, fontWeight: theme.typography.fontWeightMedium }}>{insight.title}</p>
                  {insight.summary ? (
                    <p style={{ margin: 0, color: theme.colors.textMuted }}>{insight.summary}</p>
                  ) : null}
                </div>
              ))}
            </div>
          ) : rawInsights ? (
            <pre
              style={{
                margin: 0,
                background: theme.colors.surfaceAlt,
                borderRadius: theme.radii.sm,
                border: `1px solid ${theme.colors.border}`,
                padding: theme.spacing.sm,
                whiteSpace: 'pre-wrap',
              }}
            >
              {rawInsights}
            </pre>
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
