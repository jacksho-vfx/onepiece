import React, { useEffect, useMemo, useState } from 'react';
import { Card, SectionHeader } from './ui';
import { useTheme } from '../styles/ThemeContext';

interface LogEntry {
  serviceId: string;
  serviceName: string;
  stream: 'stdout' | 'stderr';
  line: string;
  timestamp: string;
}

declare global {
  interface Window {
    electron: {
      invoke: <T = unknown>(channel: string, payload?: unknown) => Promise<T>;
      on?: (channel: string, listener: (event: unknown, payload: LogEntry) => void) => () => void;
    };
  }
}

function LogsPanel(): JSX.Element {
  const theme = useTheme();
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [serviceFilter, setServiceFilter] = useState<string>('all');
  const [streamFilter, setStreamFilter] = useState<'all' | 'stdout' | 'stderr'>('all');

  useEffect(() => {
    let isMounted = true;

    const loadRecentLogs = async (): Promise<void> => {
      try {
        const recentLogs = await window.electron.invoke<LogEntry[]>('logs/recent');
        if (isMounted) {
          setLogs(recentLogs);
        }
      } catch (error) {
        console.error('Failed to load recent logs', error);
      }
    };

    void loadRecentLogs();

    const unsubscribe = window.electron.on?.('logs/append', (_event, payload: LogEntry) => {
      setLogs((prev) => [...prev, payload]);
    });

    return () => {
      isMounted = false;
      if (unsubscribe) {
        unsubscribe();
      }
    };
  }, []);

  const services = useMemo(() => {
    const unique = new Set<string>();
    logs.forEach((log) => unique.add(log.serviceName));
    return Array.from(unique);
  }, [logs]);

  const filteredLogs = useMemo(() => {
    return logs.filter((log) => {
      const matchesService = serviceFilter === 'all' || log.serviceName === serviceFilter;
      const matchesStream = streamFilter === 'all' || log.stream === streamFilter;
      return matchesService && matchesStream;
    });
  }, [logs, serviceFilter, streamFilter]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: theme.spacing.lg }}>
      <SectionHeader title="Logs" subtitle="Tail recent service output and filter by stream." />

      <Card>
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
            gap: theme.spacing.md,
            alignItems: 'flex-end',
          }}
        >
          <label style={{ display: 'grid', gap: '0.35rem', color: theme.colors.text }}>
            <span style={{ fontWeight: theme.typography.fontWeightMedium }}>Service</span>
            <select
              value={serviceFilter}
              onChange={(event) => setServiceFilter(event.target.value)}
              style={{
                padding: `${theme.spacing.sm} ${theme.spacing.md}`,
                borderRadius: theme.radii.md,
                border: `1px solid ${theme.colors.border}`,
                background: theme.colors.surfaceAlt,
                color: theme.colors.text,
              }}
            >
              <option value="all">All</option>
              {services.map((service) => (
                <option key={service} value={service}>
                  {service}
                </option>
              ))}
            </select>
          </label>

          <label style={{ display: 'grid', gap: '0.35rem', color: theme.colors.text }}>
            <span style={{ fontWeight: theme.typography.fontWeightMedium }}>Stream</span>
            <select
              value={streamFilter}
              onChange={(event) => setStreamFilter(event.target.value as 'all' | 'stdout' | 'stderr')}
              style={{
                padding: `${theme.spacing.sm} ${theme.spacing.md}`,
                borderRadius: theme.radii.md,
                border: `1px solid ${theme.colors.border}`,
                background: theme.colors.surfaceAlt,
                color: theme.colors.text,
              }}
            >
              <option value="all">All</option>
              <option value="stdout">stdout</option>
              <option value="stderr">stderr</option>
            </select>
          </label>
        </div>
      </Card>

      <Card title="Live output">
        <div
          style={{
            background: theme.colors.surfaceAlt,
            borderRadius: theme.radii.md,
            border: `1px solid ${theme.colors.border}`,
            padding: theme.spacing.md,
            maxHeight: '520px',
            overflow: 'auto',
            fontFamily:
              "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace",
            color: theme.colors.text,
            display: 'grid',
            gap: theme.spacing.xs,
          }}
        >
          {filteredLogs.map((log, index) => (
            <div
              key={`${log.timestamp}-${log.serviceId}-${index}`}
              style={{
                display: 'grid',
                gridTemplateColumns: '220px 1fr',
                gap: theme.spacing.sm,
                alignItems: 'baseline',
                color: log.stream === 'stderr' ? theme.colors.danger : theme.colors.text,
              }}
            >
              <span style={{ color: theme.colors.textMuted }}>
                [{log.serviceName}] {new Date(log.timestamp).toLocaleTimeString()}
              </span>
              <span style={{ whiteSpace: 'pre-wrap' }}>{log.line}</span>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}

export default LogsPanel;
