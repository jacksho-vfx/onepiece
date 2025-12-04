import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { App } from 'electron';
import { ensureDefaultConfig } from '../configManager';
import { primePythonPath, resetPythonPathCacheForTesting, resolvePythonPath } from '../pythonPathResolver';

vi.mock('../configManager', () => ({
  ensureDefaultConfig: vi.fn(),
}));

const mockedEnsureDefaultConfig = vi.mocked(ensureDefaultConfig);

const fakeApp = {
  getPath: vi.fn(),
} as unknown as App;

const ORIGINAL_ENV = { ...process.env };

describe('pythonPathResolver', () => {
  beforeEach(() => {
    resetPythonPathCacheForTesting();
    mockedEnsureDefaultConfig.mockReset();
    process.env = { ...ORIGINAL_ENV };
  });

  afterEach(() => {
    resetPythonPathCacheForTesting();
  });

  it('prefers the configured pythonPath over environment fallbacks', async () => {
    process.env.ONEPIECE_PYTHON_PATH = 'env-python';
    mockedEnsureDefaultConfig.mockResolvedValue({ pythonPath: '/configured/python' } as never);

    primePythonPath(fakeApp);

    const interpreter = await resolvePythonPath();

    expect(interpreter).toBe('/configured/python');
    expect(mockedEnsureDefaultConfig).toHaveBeenCalled();
  });

  it('uses environment fallback when no config value is available', async () => {
    process.env.ONEPIECE_PYTHON_PATH = 'env-python';
    mockedEnsureDefaultConfig.mockResolvedValue({} as never);

    primePythonPath(fakeApp);

    const interpreter = await resolvePythonPath();

    expect(interpreter).toBe('env-python');
  });
});
