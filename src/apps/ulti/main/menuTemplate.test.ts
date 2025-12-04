import { describe, expect, it, vi } from 'vitest';
import { buildMenuTemplate } from './menuTemplate';

describe('buildMenuTemplate', () => {
  it('omits developer options when dev tools are not allowed', () => {
    const template = buildMenuTemplate({ allowDevTools: false });

    const labels = template.map((item) => item.label);
    const viewMenu = template.find((item) => item.label === 'View');

    expect(labels).toEqual(['File']);
    expect(viewMenu).toBeUndefined();
    expect(JSON.stringify(template)).not.toContain('toggleDevTools');
  });

  it('includes reload and developer tools when allowed', () => {
    const toggleDevTools = vi.fn();
    const mainWindow = { webContents: { toggleDevTools } };

    const template = buildMenuTemplate({ allowDevTools: true, mainWindow });

    const viewMenu = template.find((item) => item.label === 'View');
    const developerMenu = template.find((item) => item.label === 'Developer');

    expect(viewMenu?.submenu?.some((subItem) => subItem.role === 'reload')).toBe(true);
    expect(viewMenu?.submenu?.some((subItem) => subItem.role === 'toggleDevTools')).toBe(true);

    const devToggle = developerMenu?.submenu?.find((subItem) => subItem.label === 'Toggle Dev Tools');
    expect(devToggle).toBeTruthy();
    devToggle?.click?.();
    expect(toggleDevTools).toHaveBeenCalledTimes(1);
  });
});
