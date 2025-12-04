import type { IpcMain } from 'electron';
import { runCommand, startService } from './pythonManager';

interface WebDashboardPayload {
  host?: string;
  port?: number;
  reload?: boolean;
  logLevel?: string;
  settingsPath?: string;
}

const ALLOWED_LOG_LEVELS = new Set(['debug', 'info', 'warning', 'error']);

interface CostInsightsPayload {
  project?: string;
}

const buildDashboardArgs = ({ host, port, reload, logLevel, settingsPath }: WebDashboardPayload): string[] => {
  const args = ['-m', 'perona', 'web', 'dashboard'];

  args.push('--host', host || '127.0.0.1');
  args.push('--port', String(typeof port === 'number' ? port : 8065));

  if (reload === true) {
    args.push('--reload');
  } else if (reload === false) {
    args.push('--no-reload');
  }

  if (logLevel) {
    const normalizedLogLevel = logLevel.trim().toLowerCase();

    if (!ALLOWED_LOG_LEVELS.has(normalizedLogLevel)) {
      throw new Error(
        `Invalid log level '${logLevel}'. Allowed values: ${Array.from(ALLOWED_LOG_LEVELS).join(', ')}.`,
      );
    }

    args.push('--log-level', normalizedLogLevel);
  }

  if (settingsPath) {
    args.push('--settings-path', settingsPath);
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

const parseInsightsFromStdout = (stdout?: string): { insights: unknown | null; rawText: string | null } => {
  const rawText = stdout?.trim() ?? null;

  if (!rawText) {
    return { insights: null, rawText: null };
  }

  const tryParse = (candidate: string): unknown | null => {
    try {
      return JSON.parse(candidate);
    } catch (error) {
      console.warn('Failed to parse cost insights JSON candidate', error);
      return null;
    }
  };

  if (rawText.startsWith('{') || rawText.startsWith('[')) {
    const parsed = tryParse(rawText);
    if (parsed) {
      return { insights: parsed, rawText };
    }
  }

  const lines = rawText.split('\n').map((line) => line.trim()).filter(Boolean);
  const reversedCandidate = [...lines].reverse().find((line) => line.startsWith('{') || line.startsWith('['));

  if (reversedCandidate) {
    const parsed = tryParse(reversedCandidate);
    if (parsed) {
      return { insights: parsed, rawText };
    }
  }

  return { insights: null, rawText };
};

const buildParseError = ({
  stderr,
  code,
}: {
  stderr?: string;
  code?: number | null;
}): { message: string | null; stderr: string | null; code: number | null } | null => {
  const normalizedStderr = stderr?.trim() ?? null;
  const exitCode = typeof code === 'number' ? code : null;

  if (!normalizedStderr && exitCode === null) {
    return null;
  }

  const messageParts = [] as string[];
  if (normalizedStderr) {
    messageParts.push(normalizedStderr);
  }
  if (exitCode !== null) {
    messageParts.push(`(exit code ${exitCode})`);
  }

  const message = messageParts.length > 0 ? messageParts.join(' ') : null;

  return { message, stderr: normalizedStderr, code: exitCode };
};

export function registerPeronaIpcHandlers(ipcMain: IpcMain): void {
  ipcMain.handle('perona/web-dashboard', async (_event, payload: WebDashboardPayload = {}) => {
    const args = buildDashboardArgs(payload);
    return startService('Perona web dashboard', args);
  });

  ipcMain.handle('perona/cost-insights', async (_event, payload: CostInsightsPayload = {}) => {
    const args = buildCostInsightsArgs(payload);
    const result = await runCommand(args);

    const { insights, rawText } = parseInsightsFromStdout(result.stdout);
    const parseError = insights === null ? buildParseError(result) : null;

    return {
      ...result,
      insights,
      rawText: rawText ?? parseError?.stderr ?? null,
      parseError,
    };
  });
}
