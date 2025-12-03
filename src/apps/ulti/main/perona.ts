import type { IpcMain } from 'electron';
import { runCommand, startService } from './pythonManager';

interface WebDashboardPayload {
  host?: string;
  port?: number;
  reload?: boolean;
  logLevel?: string;
}

interface CostInsightsPayload {
  project?: string;
}

const buildDashboardArgs = ({ host, port, reload, logLevel }: WebDashboardPayload): string[] => {
  const args = ['-m', 'perona', 'web', 'dashboard'];

  if (host) {
    args.push('--host', host);
  }

  if (typeof port === 'number') {
    args.push('--port', String(port));
  }

  if (reload) {
    args.push('--reload');
  }

  if (logLevel) {
    args.push('--log-level', logLevel);
  }

  return args;
};

const buildCostInsightsArgs = ({ project }: CostInsightsPayload): string[] => {
  const args = ['-m', 'perona', 'cost', 'insights'];

  if (project) {
    args.push('--project', project);
  }

  return args;
};

const parseInsightsFromStdout = (stdout?: string): unknown => {
  const trimmed = stdout?.trim();

  if (!trimmed) {
    return null;
  }

  const tryParse = (candidate: string): unknown => {
    try {
      return JSON.parse(candidate);
    } catch (error) {
      console.warn('Failed to parse cost insights JSON candidate', error);
      return null;
    }
  };

  if (trimmed.startsWith('{') || trimmed.startsWith('[')) {
    const parsed = tryParse(trimmed);
    if (parsed) {
      return parsed;
    }
  }

  const lines = trimmed.split('\n').map((line) => line.trim()).filter(Boolean);
  const reversedCandidate = [...lines].reverse().find((line) => line.startsWith('{') || line.startsWith('['));

  if (reversedCandidate) {
    const parsed = tryParse(reversedCandidate);
    if (parsed) {
      return parsed;
    }
  }

  return null;
};

export function registerPeronaIpcHandlers(ipcMain: IpcMain): void {
  ipcMain.handle('perona/web-dashboard', async (_event, payload: WebDashboardPayload = {}) => {
    const args = buildDashboardArgs(payload);
    return startService('Perona web dashboard', args);
  });

  ipcMain.handle('perona/cost-insights', async (_event, payload: CostInsightsPayload = {}) => {
    const args = buildCostInsightsArgs(payload);
    const result = await runCommand(args);

    const parsedInsights = parseInsightsFromStdout(result.stdout);

    return {
      ...result,
      insights: parsedInsights,
    };
  });
}
