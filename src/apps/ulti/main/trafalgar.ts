import type { IpcMain } from 'electron';
import { runCommand } from './pythonManager';
import { createTask } from './taskManager';

export interface PipelineSummary {
  id: string;
  name: string;
  description?: string;
  parameters?: string[];
}

function parsePipelineHeader(line: string): { id: string; name: string } {
  const header = line.trim();
  const match = header.match(/^(.+?)\s*\((.+)\)$/);

  if (match) {
    return { id: match[1].trim(), name: match[2].trim() };
  }

  return { id: header, name: header };
}

function parsePipelineListFromJson(candidate: unknown): PipelineSummary[] | null {
  if (Array.isArray(candidate)) {
    return candidate
      .map((entry) => {
        if (!entry || typeof entry !== 'object') {
          return null;
        }

        const id = String((entry as { id?: unknown; name?: unknown }).id ?? '').trim();
        const name = String((entry as { name?: unknown }).name ?? id).trim();
        const description = (entry as { description?: unknown }).description;
        const parameters = (entry as { parameters?: unknown }).parameters;

        if (!id) {
          return null;
        }

        return {
          id,
          name: name || id,
          description:
            typeof description === 'string' && description.trim() ? description.trim() : undefined,
          parameters: Array.isArray(parameters)
            ? parameters.map((param) => String(param).trim()).filter(Boolean)
            : undefined,
        } satisfies PipelineSummary;
      })
      .filter((entry): entry is PipelineSummary => Boolean(entry));
  }

  if (
    candidate &&
    typeof candidate === 'object' &&
    Array.isArray((candidate as { pipelines?: unknown }).pipelines)
  ) {
    return parsePipelineListFromJson((candidate as { pipelines?: unknown }).pipelines ?? []);
  }

  return null;
}

function parsePipelineListOutput(stdout: string): PipelineSummary[] {
  const trimmed = stdout.trim();
  if (!trimmed || trimmed.includes('No pipelines are currently registered')) {
    return [];
  }

  let parsedJson: unknown = null;
  try {
    parsedJson = JSON.parse(trimmed);
  } catch (error) {
    parsedJson = null;
  }

  const maybeJson = parsedJson ? parsePipelineListFromJson(parsedJson) : null;

  if (maybeJson) {
    return maybeJson;
  }

  const pipelines: PipelineSummary[] = [];
  let current: PipelineSummary | null = null;

  const lines = trimmed.split(/\r?\n/);
  for (const rawLine of lines) {
    const line = rawLine.trimEnd();
    if (!line.trim()) {
      continue;
    }

    const isHeader = !rawLine.startsWith(' ');

    if (isHeader) {
      if (current) {
        pipelines.push(current);
      }
      current = { ...parsePipelineHeader(line) };
      continue;
    }

    if (!current) {
      continue;
    }

    const content = line.trim();
    const lower = content.toLowerCase();

    if (lower.startsWith('parameters:')) {
      const paramsText = content.slice('parameters:'.length).trim();
      const parameters = paramsText
        ? paramsText
            .split(',')
            .map((param) => param.trim())
            .filter(Boolean)
        : [];
      current.parameters = parameters;
      continue;
    }

    current.description = current.description
      ? `${current.description} ${content}`.trim()
      : content;
  }

  if (current) {
    pipelines.push(current);
  }

  return pipelines;
}

async function getPipelineListOutput(): Promise<string> {
  const baseArgs = ['-m', 'trafalgar', 'pipeline', 'list'];
  const attempts: string[][] = [[...baseArgs, '--format', 'json'], baseArgs];

  let lastResult: { code: number; stdout: string; stderr: string } | null = null;

  for (const args of attempts) {
    const result = await runCommand(args);
    lastResult = result;

    if (result.code === 0) {
      return result.stdout || result.stderr || '';
    }
  }

  throw new Error(lastResult?.stderr || lastResult?.stdout || 'Failed to list pipelines.');
}

export function registerTrafalgarPipelineIpcHandlers(ipcMain: IpcMain): void {
  ipcMain.handle('trafalgar/pipeline-list', async () => {
    const output = await getPipelineListOutput();

    return parsePipelineListOutput(output);
  });

  ipcMain.handle(
    'trafalgar/pipeline-run',
    async (
      _event,
      payload:
        | { id?: string; params?: Record<string, string> }
        | { pipelineId?: string; parameters?: Record<string, string> },
    ) => {
      const pipelineId = (payload?.id ?? (payload as { pipelineId?: string })?.pipelineId ?? '').trim();

      if (!pipelineId) {
        throw new Error('pipelineId is required to run a pipeline.');
      }

      const args = ['-m', 'trafalgar', 'pipeline', 'run', pipelineId];
      const parameters = (payload as { params?: Record<string, string> })?.params ??
        (payload as { parameters?: Record<string, string> })?.parameters ??
        {};

      Object.entries(parameters)
        .filter(([key]) => Boolean(key))
        .sort(([a], [b]) => a.localeCompare(b))
        .forEach(([key, value]) => {
          args.push('--param', `${key}=${value ?? ''}`);
        });

      const label = `Trafalgar pipeline: ${pipelineId}`;
      return createTask(label, args);
    },
  );
}
