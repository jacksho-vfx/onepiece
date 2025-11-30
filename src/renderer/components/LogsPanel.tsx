import React, { useEffect, useMemo, useState } from 'react';

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
    <div className="logs-panel">
      <div className="logs-panel__controls">
        <label>
          Service:
          <select value={serviceFilter} onChange={(event) => setServiceFilter(event.target.value)}>
            <option value="all">All</option>
            {services.map((service) => (
              <option key={service} value={service}>
                {service}
              </option>
            ))}
          </select>
        </label>

        <label>
          Stream:
          <select
            value={streamFilter}
            onChange={(event) => setStreamFilter(event.target.value as 'all' | 'stdout' | 'stderr')}
          >
            <option value="all">All</option>
            <option value="stdout">stdout</option>
            <option value="stderr">stderr</option>
          </select>
        </label>
      </div>

      <div className="logs-panel__viewer">
        {filteredLogs.map((log, index) => (
          <div key={`${log.timestamp}-${log.serviceId}-${index}`} className={`logs-panel__line logs-panel__line--${log.stream}`}>
            <span className="logs-panel__meta">[{log.serviceName}] {new Date(log.timestamp).toLocaleTimeString()}</span>
            <span className="logs-panel__text">{log.line}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export default LogsPanel;
