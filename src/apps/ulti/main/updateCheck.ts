import https from 'https';
import type { App, IpcMain } from 'electron';

// Repository that hosts the main releases (owner/repo). Update this string if the
// release artifacts live elsewhere, or set ONEPIECE_DESKTOP_REPO in the environment.
const DEFAULT_REPOSITORY = 'onepiece/studio-main';

// Abort the GitHub request after a reasonable amount of time so the UI can surface
// a clear error to the user instead of hanging indefinitely.
export const UPDATE_CHECK_TIMEOUT_MS = 5000;
export const UPDATE_CHECK_TIMEOUT_MESSAGE =
  'Update check timed out. Please try again in a few moments.';

// Drop any leading "v" prefix and trim whitespace so we can compare versions reliably.
function normalizeVersion(version: string): string {
  return version.trim().replace(/^v/i, '');
}

// Minimal semantic version comparator (major/minor/patch). Extra segments are compared
// in order; missing segments are treated as 0.
function compareSemver(a: string, b: string): number {
  const aParts = normalizeVersion(a).split('.').map((part) => Number.parseInt(part, 10) || 0);
  const bParts = normalizeVersion(b).split('.').map((part) => Number.parseInt(part, 10) || 0);
  const maxLength = Math.max(aParts.length, bParts.length);

  for (let i = 0; i < maxLength; i += 1) {
    const aValue = aParts[i] ?? 0;
    const bValue = bParts[i] ?? 0;

    if (aValue > bValue) return 1;
    if (aValue < bValue) return -1;
  }

  return 0;
}

// Fetch the latest release tag for the main GitHub repository.
async function fetchLatestTag(repository: string): Promise<{ latestVersion?: string; url?: string; error?: string }> {
  const repoPath = repository || DEFAULT_REPOSITORY;
  const requestOptions: https.RequestOptions = {
    hostname: 'api.github.com',
    path: `/repos/${repoPath}/releases/latest`,
    method: 'GET',
    headers: {
      'User-Agent': 'OnePiece-Studio-Desktop',
      Accept: 'application/vnd.github+json',
    },
  };

  return await new Promise((resolve) => {
    let timeoutId: NodeJS.Timeout | undefined;

    const clearRequestTimeout = (): void => {
      if (!timeoutId) return;
      clearTimeout(timeoutId);
      timeoutId = undefined;
    };

    const request = https.get(requestOptions, (response) => {
      if (!response) {
        resolve({ error: 'No response received from GitHub.' });
        return;
      }

      const chunks: Buffer[] = [];

      response.on('data', (chunk: Buffer) => {
        chunks.push(chunk);
      });

      response.on('end', () => {
        clearRequestTimeout();
        const body = Buffer.concat(chunks).toString('utf-8');

        if (response.statusCode && response.statusCode >= 400) {
          resolve({ error: `GitHub responded with status ${response.statusCode}` });
          return;
        }

        try {
          const parsed = JSON.parse(body) as { tag_name?: string; name?: string; html_url?: string };
          const latestVersion = parsed.tag_name || parsed.name;

          if (!latestVersion) {
            resolve({ error: 'Latest release tag not found.' });
            return;
          }

          resolve({
            latestVersion: normalizeVersion(latestVersion),
            url: parsed.html_url || `https://github.com/${repoPath}/releases/tag/${latestVersion}`,
          });
        } catch (error) {
          resolve({ error: error instanceof Error ? error.message : 'Failed to parse GitHub response.' });
        }
      });

      response.on('aborted', () => {
        clearRequestTimeout();
        resolve({ error: 'GitHub response was aborted.' });
      });

      response.on('error', (error) => {
        clearRequestTimeout();
        resolve({ error: error.message || 'GitHub response failed.' });
      });
    });

    timeoutId = setTimeout(() => {
      request.destroy(new Error(UPDATE_CHECK_TIMEOUT_MESSAGE));
    }, UPDATE_CHECK_TIMEOUT_MS);

    request.on('error', (error) => {
      clearRequestTimeout();
      resolve({ error: error.message || 'Unable to connect to GitHub.' });
    });

    request.on('close', () => {
      clearRequestTimeout();
    });

    request.end();
  });
}

export async function checkForDesktopUpdate(
  currentVersion: string,
): Promise<{ hasUpdate: boolean; latestVersion?: string; url?: string; error?: string }> {
  const repository = process.env.ONEPIECE_DESKTOP_REPO || DEFAULT_REPOSITORY;
  const { latestVersion, url, error } = await fetchLatestTag(repository);

  if (error || !latestVersion) {
    return { hasUpdate: false, error };
  }

  const comparison = compareSemver(latestVersion, currentVersion);

  return {
    hasUpdate: comparison > 0,
    latestVersion,
    url,
  };
}

export function registerUpdateIpcHandlers(ipcMain: IpcMain, app: App): void {
  ipcMain.handle('updates/check', async () => {
    const currentVersion = app.getVersion();

    try {
      const result = await checkForDesktopUpdate(currentVersion);
      return { ...result, currentVersion };
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Unexpected error during update check.';
      return { hasUpdate: false, error: message, currentVersion };
    }
  });
}
