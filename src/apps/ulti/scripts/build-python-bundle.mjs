#!/usr/bin/env node

import { spawn } from 'child_process';
import fs from 'fs/promises';
import path from 'path';

function parseArgs() {
  const args = process.argv.slice(2);
  const parsed = {
    python: 'python3',
    targetDir: undefined,
    requirements: undefined,
  };

  for (let i = 0; i < args.length; i += 1) {
    const arg = args[i];
    if (arg === '--python') {
      parsed.python = args[i + 1];
      i += 1;
    } else if (arg === '--targetDir') {
      parsed.targetDir = args[i + 1];
      i += 1;
    } else if (arg === '--requirements') {
      parsed.requirements = args[i + 1];
      i += 1;
    } else {
      console.error(`Unknown argument: ${arg}`);
      process.exit(1);
    }
  }

  if (!parsed.targetDir) {
    console.error('Missing required --targetDir argument');
    process.exit(1);
  }

  if (!parsed.python) {
    console.error('Missing value for --python');
    process.exit(1);
  }

  return parsed;
}

function runCommand(command, args, options = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      stdio: 'inherit',
      ...options,
    });

    child.on('close', (code) => {
      if (code === 0) {
        resolve();
      } else {
        reject(new Error(`${command} exited with code ${code}`));
      }
    });

    child.on('error', (error) => {
      reject(error);
    });
  });
}

async function main() {
  const { python, targetDir, requirements } = parseArgs();
  const resolvedTargetDir = path.resolve(targetDir);

  console.log(`Preparing python bundle at ${resolvedTargetDir}`);

  console.log('Cleaning previous bundle (if any)...');
  await fs.rm(resolvedTargetDir, { recursive: true, force: true });
  await fs.mkdir(resolvedTargetDir, { recursive: true });

  console.log('Creating virtual environment...');
  await runCommand(python, ['-m', 'venv', 'venv'], { cwd: resolvedTargetDir });

  const binDir = process.platform === 'win32' ? 'Scripts' : 'bin';
  const pipExecutable = process.platform === 'win32' ? 'pip.exe' : 'pip';
  const pipPath = path.join(resolvedTargetDir, 'venv', binDir, pipExecutable);

  console.log('Installing dependencies into venv...');
  if (requirements) {
    await runCommand(pipPath, ['install', '-r', path.resolve(requirements)]);
  } else {
    // Install the published package or a local path if available in the environment running this script.
    await runCommand(pipPath, ['install', 'onepiece']);
  }

  const meta = {
    createdAt: new Date().toISOString(),
    python,
    note: 'Venv for OnePiece Studio Desktop',
  };

  const metaPath = path.join(resolvedTargetDir, 'meta.json');
  await fs.writeFile(metaPath, JSON.stringify(meta, null, 2));
  console.log(`Wrote metadata to ${metaPath}`);

  console.log('Python bundle prepared successfully.');
}

main().catch((error) => {
  console.error('Failed to build python bundle:', error);
  process.exit(1);
});
