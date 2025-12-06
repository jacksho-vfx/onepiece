/** @vitest-environment jsdom */

import '@testing-library/jest-dom/vitest';
import React from 'react';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import FirstRunWizard from './FirstRunWizard';
import { ThemeProvider } from '../styles/ThemeContext';
import { ToasterProvider } from './ui';

describe('FirstRunWizard environment detection', () => {
  const invokeMock = vi.fn();

  beforeEach(() => {
    invokeMock.mockReset();
    (window as typeof window & { electron?: unknown }).electron = {
      invoke: invokeMock,
    } as typeof window.electron;
  });

  afterEach(() => {
    cleanup();
    delete (window as typeof window & { electron?: unknown }).electron;
  });

  it('shows a warning when environment detection is rejected', async () => {
    invokeMock.mockImplementation((channel: string) => {
      if (channel === 'system/detect-env') {
        return Promise.reject(new Error('IPC blocked'));
      }

      return Promise.resolve(null);
    });

    render(
      <ThemeProvider>
        <ToasterProvider>
          <FirstRunWizard onComplete={vi.fn()} />
        </ToasterProvider>
      </ThemeProvider>,
    );

    const warning = await screen.findByRole('alert');

    await waitFor(() => {
      expect(warning).toHaveTextContent(
        /automatic environment detection failed\. please enter your paths manually\./i,
      );
    });
  });
});
