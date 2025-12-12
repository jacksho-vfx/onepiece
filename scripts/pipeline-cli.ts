#!/usr/bin/env node
/*
 * Pipeline CLI entry point for render farm and automation nodes.
 *
 * This script delegates to the Python Trafalgar pipeline orchestrator via the
 * existing task manager so that tasks can be tracked consistently alongside the
 * desktop application. It exposes minimal subcommands tailored for CI and farm
 * workers: ingest, render, and delivery.
 */

import { createTask, waitForTaskCompletion } from '../src/apps/ulti/main/taskManager';

const PIPELINE_COMMAND = ['-m', 'trafalgar', 'pipeline', 'run'] as const;

const HELP_TEXT = `Usage: pipeline-cli <command> [options]

Commands:
  ingest    Trigger the ingest pipeline (requires --source and --shot).
  render    Trigger the render pipeline (requires --scene and --frames).
  delivery  Trigger the delivery pipeline (requires --playlist and --target).

Options:
  --help    Show this message.

Examples:
  npm run pipeline:cli -- ingest --source /mnt/input/plates --shot ep01_sc010
  npm run pipeline:cli -- render --scene /mnt/scenes/shot.usd --frames 1001-1050
  npm run pipeline:cli -- delivery --playlist preview --target /mnt/review/out
`;

type CommandName = 'ingest' | 'render' | 'delivery';

type FlagMap = Record<string, string>;

type CommandDefinition = {
  readonly pipelineId: string;
  readonly requiredFlags: string[];
  readonly label: (flags: FlagMap) => string;
};

const COMMANDS: Record<CommandName, CommandDefinition> = {
  ingest: {
    pipelineId: 'ingest',
    requiredFlags: ['source', 'shot'],
    label: (flags) => `Ingest: ${flags.source ?? ''} (${flags.shot ?? ''})`,
  },
  render: {
    pipelineId: 'render',
    requiredFlags: ['scene', 'frames'],
    label: (flags) => `Render: ${flags.scene ?? ''} [${flags.frames ?? ''}]`,
  },
  delivery: {
    pipelineId: 'delivery',
    requiredFlags: ['playlist', 'target'],
    label: (flags) => `Delivery: ${flags.playlist ?? ''} -> ${flags.target ?? ''}`,
  },
};

const buildParamArgs = (flags: FlagMap): string[] => {
  const entries = Object.entries(flags)
    .filter(([key]) => key !== 'help')
    .sort(([a], [b]) => a.localeCompare(b));

  const args: string[] = [];

  for (const [key, value] of entries) {
    args.push('--param', `${key}=${value}`);
  }

  return args;
};

const parseFlags = (argv: string[]): FlagMap => {
  const flags: FlagMap = {};

  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];

    if (!arg.startsWith('--')) {
      throw new Error(`Unexpected argument '${arg}'.`);
    }

    const [rawKey, inlineValue] = arg.slice(2).split('=', 2);
    const key = rawKey.trim();

    if (!key) {
      throw new Error('Flag name cannot be empty.');
    }

    if (inlineValue !== undefined) {
      flags[key] = inlineValue;
      continue;
    }

    const next = argv[index + 1];

    if (next === undefined || next.startsWith('--')) {
      throw new Error(`Flag '--${key}' is missing a value.`);
    }

    flags[key] = next;
    index += 1;
  }

  return flags;
};

const ensureRequiredFlags = (definition: CommandDefinition, flags: FlagMap): void => {
  const missing = definition.requiredFlags.filter((flag) => !flags[flag]);

  if (missing.length > 0) {
    throw new Error(
      `Missing required flag(s) for '${definition.pipelineId}': ${missing.map((flag) => `--${flag}`).join(', ')}`,
    );
  }
};

const runCommand = async (command: CommandName, argv: string[]): Promise<number> => {
  const definition = COMMANDS[command];
  const flags = parseFlags(argv);

  ensureRequiredFlags(definition, flags);

  const args = [
    ...PIPELINE_COMMAND,
    definition.pipelineId,
    ...buildParamArgs(flags),
  ];

  const taskId = await createTask(definition.label(flags), args, {
    onStdout: (chunk) => process.stdout.write(chunk),
    onStderr: (chunk) => process.stderr.write(chunk),
  });

  // eslint-disable-next-line no-console
  console.log(`Started pipeline task '${definition.pipelineId}' (id: ${taskId}).`);

  const completedTask = await waitForTaskCompletion(taskId);

  if (typeof completedTask.exitCode === 'number') {
    return completedTask.exitCode;
  }

  return completedTask.status === 'succeeded' ? 0 : 1;
};

const main = async (): Promise<void> => {
  const [commandName, ...argv] = process.argv.slice(2);

  if (!commandName || commandName === '--help' || commandName === '-h') {
    // eslint-disable-next-line no-console
    console.log(HELP_TEXT);
    process.exit(commandName ? 0 : 1);
  }

  if (!Object.hasOwn(COMMANDS, commandName)) {
    // eslint-disable-next-line no-console
    console.error(`Unknown command '${commandName}'.\n\n${HELP_TEXT}`);
    process.exit(1);
  }

  try {
    const exitCode = await runCommand(commandName as CommandName, argv);
    process.exit(exitCode ?? 0);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    // eslint-disable-next-line no-console
    console.error(`Failed to run pipeline command: ${message}`);
    process.exit(1);
  }
};

void main();

