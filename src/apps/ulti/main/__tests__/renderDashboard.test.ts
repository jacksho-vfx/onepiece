import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('electron', () => ({ ipcMain: { handle: vi.fn() } }));

import { resolveRenderDashboardUrl } from '../render';

const originalEnv = { ...process.env };

afterEach(() => {
  process.env = { ...originalEnv };
});

describe('resolveRenderDashboardUrl', () => {
  it('prefers environment override for render dashboard', () => {
    process.env.ONEPIECE_RENDER_DASHBOARD_BASE_URL = 'https://render.example.com';

    expect(resolveRenderDashboardUrl()).toBe('https://render.example.com/render');
  });

  it('falls back to the default base URL when unset', () => {
    delete process.env.ONEPIECE_RENDER_DASHBOARD_BASE_URL;
    delete process.env.RENDER_DASHBOARD_BASE_URL;

    expect(resolveRenderDashboardUrl()).toBe('http://127.0.0.1:8080/render');
  });

  it('returns null when the configured URL is unsafe', () => {
    process.env.RENDER_DASHBOARD_BASE_URL = 'file:///etc/passwd';

    expect(resolveRenderDashboardUrl()).toBeNull();
  });
});
