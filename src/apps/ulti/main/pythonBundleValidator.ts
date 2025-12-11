import { promises as fs } from 'fs';
import path from 'path';
import type { App } from 'electron';

export interface PythonBundleManifest {
  generatedAt?: string;
  runtimeSource?: string;
  wheelsSource?: string;
  dccBridgeSource?: string;
  [key: string]: unknown;
}

export interface ValidationAttempt {
  bundlePath: string;
  manifestPath: string;
  manifest?: PythonBundleManifest;
  missing: string[];
  error?: string;
  status: 'valid' | 'invalid';
}

function isDirectory(target: string): Promise<boolean> {
  return fs
    .stat(target)
    .then((stats) => stats.isDirectory())
    .catch(() => false);
}

async function inspectBundle(bundlePath: string): Promise<ValidationAttempt> {
  const manifestPath = path.join(bundlePath, 'manifest.json');
  let manifest: PythonBundleManifest | undefined;
  const missing: string[] = [];
  let error: string | undefined;

  try {
    const manifestContents = await fs.readFile(manifestPath, 'utf-8');
    manifest = JSON.parse(manifestContents) as PythonBundleManifest;
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error reading manifest';
    error = `Unable to read manifest: ${message}`;
    missing.push(manifestPath);
    return {
      status: 'invalid',
      bundlePath,
      manifestPath,
      manifest,
      missing,
      error,
    };
  }

  const requiredDirectories = ['runtime', 'wheels', 'dcc'];

  for (const directory of requiredDirectories) {
    const target = path.join(bundlePath, directory);
    const exists = await isDirectory(target);
    if (!exists) {
      missing.push(target);
    }
  }

  if (missing.length === 0) {
    return {
      status: 'valid',
      bundlePath,
      manifestPath,
      manifest,
      missing,
    };
  }

  return {
    status: 'invalid',
    bundlePath,
    manifestPath,
    manifest,
    missing,
  };
}

export function getPythonBundleSearchPaths(app: App): string[] {
  const candidates = [
    path.join(process.resourcesPath, 'python'),
    path.join(app.getAppPath(), 'python'),
    path.join(path.dirname(app.getAppPath()), 'python'),
    path.join(process.cwd(), 'python'),
  ];

  return Array.from(new Set(candidates));
}

export async function validatePythonBundle(
  searchPaths: string[],
): Promise<{ status: 'valid'; attempt: ValidationAttempt } | { status: 'invalid'; attempts: ValidationAttempt[] }> {
  const attempts: ValidationAttempt[] = [];

  for (const bundlePath of searchPaths) {
    const attempt = await inspectBundle(bundlePath);
    attempts.push(attempt);

    if (attempt.status === 'valid') {
      return { status: 'valid', attempt };
    }
  }

  return { status: 'invalid', attempts };
}
