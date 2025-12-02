import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Button, Card, SectionHeader, StatusBadge } from './ui';
import { useTheme } from '../styles/ThemeContext';
import { getNextStep, ProjectActivitySummary } from '../utils/nextStep';

type ProjectSelection = { name: string; path: string };

type ProjectActivity = {
  type: string;
  time: string;
  description?: string;
};

type ProjectStats = {
  ingests: number;
  publishes: number;
  renders: number;
  deliveries: number;
};

type ProjectInfoResponse = {
  project?: string;
  stats?: Partial<ProjectStats>;
  recent_activity?: ProjectActivity[];
  warnings?: string[];
};

const DEFAULT_STATS: ProjectStats = {
  ingests: 0,
  publishes: 0,
  renders: 0,
  deliveries: 0,
};

interface ProjectOverviewProps {
  project?: ProjectSelection;
  activitySummary?: ProjectActivitySummary;
  onOpenVendorIngest?: () => void;
  onOpenDccPublish?: () => void;
  onOpenRenderSubmit?: () => void;
  onOpenDelivery?: () => void;
  onOpenDiagnostics?: () => void;
  refreshKey?: number;
}

function ProjectOverview({
  project,
  activitySummary,
  onOpenVendorIngest,
  onOpenDccPublish,
  onOpenRenderSubmit,
  onOpenDelivery,
  onOpenDiagnostics,
  refreshKey,
}: ProjectOverviewProps): JSX.Element {
  const theme = useTheme();
  const [stats, setStats] = useState<ProjectStats>(DEFAULT_STATS);
  const [recentActivity, setRecentActivity] = useState<ProjectActivity[]>([]);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [hasFetched, setHasFetched] = useState(false);
  const [statsWarning, setStatsWarning] = useState<string | null>(null);

  const healthStatus = useMemo(() => {
    return warnings.length > 0 ? 'Warnings' : 'OK';
  }, [warnings]);

  const normalizeStats = useCallback((input?: Partial<ProjectStats>): ProjectStats => {
    return {
      ingests: Number(input?.ingests ?? DEFAULT_STATS.ingests) || 0,
      publishes: Number(input?.publishes ?? DEFAULT_STATS.publishes) || 0,
      renders: Number(input?.renders ?? DEFAULT_STATS.renders) || 0,
      deliveries: Number(input?.deliveries ?? DEFAULT_STATS.deliveries) || 0,
    };
  }, []);

  const resetOverview = useCallback(() => {
    setStats(DEFAULT_STATS);
    setRecentActivity([]);
    setWarnings([]);
    setStatsWarning(null);
    setHasFetched(false);
    setLoading(false);
  }, []);

  const fetchProjectInfo = useCallback(async (): Promise<void> => {
    if (!project) {
      resetOverview();
      return;
    }

    setLoading(true);
    setStatsWarning(null);

    try {
      const result = await window.electron.invoke<{ code: number; stdout?: string; stderr?: string }>(
        'python/run-command',
        {
          // TODO: Replace this call with the finalized CLI once `python -m onepiece project-info` exists.
          args: ['-m', 'onepiece', 'project-info', '--root', project.path, '--format', 'json'],
        },
      );

      if (result.code !== 0) {
        throw new Error(`project-info exited with code ${result.code}`);
      }

      const output = result.stdout ?? '';
      if (!output.trim()) {
        throw new Error('project-info returned no data');
      }

      const parsed = JSON.parse(output) as ProjectInfoResponse;

      const normalizedStats = normalizeStats(parsed.stats);
      const normalizedActivity = Array.isArray(parsed.recent_activity) ? parsed.recent_activity : [];
      const normalizedWarnings = Array.isArray(parsed.warnings) ? parsed.warnings : [];

      setStats(normalizedStats);
      setRecentActivity(normalizedActivity);
      setWarnings(normalizedWarnings);
      setStatsWarning(parsed.stats ? null : 'Project stats unavailable');
    } catch (err) {
      console.error('Failed to fetch project overview stats', err);
      setStats(DEFAULT_STATS);
      setRecentActivity([]);
      setWarnings([]);
      setStatsWarning('Project stats unavailable');
    } finally {
      setHasFetched(true);
      setLoading(false);
    }
  }, [normalizeStats, project, resetOverview]);

  useEffect(() => {
    if (project) {
      setHasFetched(false);
    }

    void fetchProjectInfo();
  }, [fetchProjectInfo, project, refreshKey]);

  const summary = useMemo<ProjectActivitySummary>(() => {
    if (activitySummary) {
      return activitySummary;
    }

    return stats;
  }, [activitySummary, stats]);

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

  if (!hasFetched && loading) {
    return (
      <Card title="Project overview">
        <p style={{ margin: 0, color: theme.colors.textMuted }}>Loading project overview…</p>
      </Card>
    );
  }

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
        action={
          <>
            {statsWarning ? <StatusBadge status="Warning">{statsWarning}</StatusBadge> : null}
            <Button variant="secondary" size="sm" isLoading={loading} onClick={() => void fetchProjectInfo()}>
              Refresh
            </Button>
          </>
        }
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
            {[
              { label: 'Ingests', value: stats.ingests },
              { label: 'Publishes', value: stats.publishes },
              { label: 'Renders', value: stats.renders },
              { label: 'Deliveries', value: stats.deliveries },
            ].map((item) => (
              <div key={item.label} style={{ display: 'grid', gap: '0.35rem' }}>
                <p style={{ margin: 0, color: theme.colors.textMuted }}>{item.label}</p>
                <p style={{ margin: 0, fontSize: '1.8rem', fontWeight: theme.typography.fontWeightBold }}>{item.value}</p>
              </div>
            ))}
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
