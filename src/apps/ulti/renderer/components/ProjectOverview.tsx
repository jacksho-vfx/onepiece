import React, { useEffect, useMemo, useState } from 'react';
import { Button, Card, SectionHeader, StatusBadge } from './ui';
import { useTheme } from '../styles/ThemeContext';
import { getNextStep, ProjectActivitySummary } from '../utils/nextStep';

type ProjectSelection = { name: string; path: string };

type ProjectActivity = {
  type: string;
  time: string;
  description?: string;
};

type ProjectInfo = {
  shots?: number;
  assets?: number;
  ingests?: number;
  publishes?: number;
  renders?: number;
  deliveries?: number;
  recentActivity?: ProjectActivity[];
  warnings?: string[];
};

interface ProjectOverviewProps {
  project?: ProjectSelection;
  onViewLogs?: () => void;
  activitySummary?: ProjectActivitySummary;
  onOpenVendorIngest?: () => void;
  onOpenDccPublish?: () => void;
  onOpenRenderSubmit?: () => void;
  onOpenDelivery?: () => void;
  onOpenDiagnostics?: () => void;
}

function ProjectOverview({
  project,
  onViewLogs,
  activitySummary,
  onOpenVendorIngest,
  onOpenDccPublish,
  onOpenRenderSubmit,
  onOpenDelivery,
  onOpenDiagnostics,
}: ProjectOverviewProps): JSX.Element {
  const theme = useTheme();
  const [info, setInfo] = useState<ProjectInfo | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const healthStatus = useMemo(() => {
    const warnings = info?.warnings ?? [];
    return warnings.length > 0 ? 'Warnings' : 'OK';
  }, [info?.warnings]);

  useEffect(() => {
    if (!project) {
      setInfo(null);
      setError(null);
      return;
    }

    const fetchProjectInfo = async (): Promise<void> => {
      setLoading(true);
      setError(null);

      try {
        const result = await window.electron.invoke<{ code: number; stdout?: string; stderr?: string }>(
          'python/run-command',
          { args: ['-m', 'onepiece', 'project-info', '--root', project.path] },
        );

        if (result.code !== 0) {
          throw new Error(`project-info exited with code ${result.code}`);
        }

        const output = result.stdout ?? '';
        try {
          const parsed = JSON.parse(output) as ProjectInfo;
          setInfo(parsed);
        } catch (parseError) {
          // TODO: Adjust parsing if the project-info command output differs from this assumption.
          console.error('Failed to parse project-info output', parseError, output);
          setError('Received unexpected project overview data.');
          setInfo(null);
        }
      } catch (err) {
        console.error('Failed to fetch project overview', err);
        setError('Unable to load project overview.');
        setInfo(null);
      } finally {
        setLoading(false);
      }
    };

    void fetchProjectInfo();
  }, [project]);

  const summary = useMemo<ProjectActivitySummary>(() => {
    const inferredSummary: ProjectActivitySummary = {
      ingests: info?.ingests ?? 0,
      publishes: info?.publishes ?? 0,
      renders: info?.renders ?? 0,
      deliveries: info?.deliveries ?? 0,
    };

    if (activitySummary) {
      return activitySummary;
    }

    return inferredSummary;
  }, [activitySummary, info?.deliveries, info?.ingests, info?.publishes, info?.renders]);

  const nextStep = useMemo(() => getNextStep(summary), [summary]);

  const handleNextStep = (): void => {
    switch (nextStep.step) {
      case 'ingest':
        onOpenVendorIngest?.();
        break;
      case 'publish':
        onOpenDccPublish?.();
        break;
      case 'render':
        onOpenRenderSubmit?.();
        break;
      case 'deliver':
        onOpenDelivery?.();
        break;
      case 'diagnostics':
        onOpenDiagnostics?.();
        break;
      default:
        break;
    }
  };

  if (!project) {
    return (
      <Card title="Project overview">
        <p style={{ margin: 0, fontWeight: theme.typography.fontWeightMedium }}>No project selected</p>
        <p style={{ margin: '0.35rem 0 0', color: theme.colors.textMuted }}>
          Choose or create a project to see an overview.
        </p>
      </Card>
    );
  }

  if (error) {
    return (
      <Card title="Project overview">
        <p style={{ margin: 0, color: theme.colors.danger }}>{error}</p>
        <p style={{ margin: '0.35rem 0', color: theme.colors.textMuted }}>
          Check your logs for more details or retry in a moment.
        </p>
        <Button variant="secondary" onClick={() => onViewLogs?.()}>View logs</Button>
      </Card>
    );
  }

  if (loading || !info) {
    return (
      <Card title="Project overview">
        <p style={{ margin: 0, color: theme.colors.textMuted }}>Loading project overview…</p>
      </Card>
    );
  }

  const { shots = 0, assets = 0, deliveries = 0, warnings = [], recentActivity = [] } = info;
  const activities = recentActivity.slice(0, 5);
  const hasHandler = useMemo(() => {
    switch (nextStep.step) {
      case 'ingest':
        return Boolean(onOpenVendorIngest);
      case 'publish':
        return Boolean(onOpenDccPublish);
      case 'render':
        return Boolean(onOpenRenderSubmit);
      case 'deliver':
        return Boolean(onOpenDelivery);
      case 'diagnostics':
        return Boolean(onOpenDiagnostics);
      default:
        return false;
    }
  }, [nextStep.step, onOpenDelivery, onOpenDiagnostics, onOpenDccPublish, onOpenRenderSubmit, onOpenVendorIngest]);

  return (
    <div className="op-layout" style={{ display: 'grid', gap: theme.spacing.lg }}>
      <SectionHeader
        title="Project overview"
        subtitle="Review key stats and recent operations for this project."
      />

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))',
          gap: theme.spacing.md,
        }}
      >
        <Card title="Project summary">
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))',
              gap: theme.spacing.md,
            }}
          >
            {[{ label: 'Shots', value: shots }, { label: 'Assets', value: assets }, { label: 'Deliveries', value: deliveries }].map(
              (item) => (
                <div key={item.label} style={{ display: 'grid', gap: '0.35rem' }}>
                  <p style={{ margin: 0, color: theme.colors.textMuted }}>{item.label}</p>
                  <p style={{ margin: 0, fontSize: '1.8rem', fontWeight: theme.typography.fontWeightBold }}>{item.value}</p>
                </div>
              ),
            )}
          </div>
        </Card>

        <Card title="Health">
          <div style={{ display: 'flex', alignItems: 'center', gap: theme.spacing.md, marginBottom: theme.spacing.sm }}>
            <StatusBadge status={healthStatus}>{healthStatus}</StatusBadge>
            {warnings.length === 0 ? (
              <p style={{ margin: 0, color: theme.colors.textMuted }}>No warnings reported.</p>
            ) : null}
          </div>
          {warnings.length > 0 ? (
            <ul style={{ margin: 0, paddingLeft: '1.2rem', color: theme.colors.warning }}>
              {warnings.map((warning, index) => (
                <li key={warning + index}>{warning}</li>
              ))}
            </ul>
          ) : null}
        </Card>

        <Card title="Next suggested step">
          <div style={{ display: 'grid', gap: theme.spacing.sm }}>
            <div style={{ display: 'grid', gap: '0.35rem' }}>
              <p style={{ margin: 0, fontWeight: theme.typography.fontWeightMedium }}>{nextStep.title}</p>
              <p style={{ margin: 0, color: theme.colors.textMuted }}>{nextStep.description}</p>
            </div>
            <Button fullWidth onClick={handleNextStep} disabled={!hasHandler}>
              {nextStep.ctaLabel}
            </Button>
          </div>
        </Card>
      </div>

      <Card title="Recent activity">
        {activities.length === 0 ? (
          <p style={{ margin: 0, color: theme.colors.textMuted }}>No recent activity yet.</p>
        ) : (
          <div style={{ display: 'grid', gap: theme.spacing.sm }}>
            {activities.map((activity, index) => (
              <div
                key={`${activity.type}-${activity.time}-${index}`}
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  padding: `${theme.spacing.xs} ${theme.spacing.sm}`,
                  borderRadius: theme.radii.sm,
                  border: `1px solid ${theme.colors.border}`,
                  background: theme.colors.surface,
                }}
              >
                <div>
                  <p style={{ margin: 0, fontWeight: theme.typography.fontWeightMedium }}>{activity.type}</p>
                  {activity.description ? (
                    <p style={{ margin: 0, color: theme.colors.textMuted }}>{activity.description}</p>
                  ) : null}
                </div>
                <p style={{ margin: 0, color: theme.colors.textMuted }}>{activity.time}</p>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}

export default ProjectOverview;
