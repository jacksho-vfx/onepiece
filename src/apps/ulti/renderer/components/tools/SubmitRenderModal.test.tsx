/** @vitest-environment jsdom */

import '@testing-library/jest-dom/vitest';
import React from 'react';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { ThemeProvider } from '../../styles/ThemeContext';
import { ToasterProvider } from '../ui/Toaster';
import SubmitRenderModal from './SubmitRenderModal';

describe('SubmitRenderModal dialog availability', () => {
  const invokeMock = vi.fn();

  beforeEach(() => {
    invokeMock.mockReset();
    (window as typeof window & { electron?: unknown }).electron = {
      invoke: invokeMock,
    } as typeof window.electron;

    invokeMock.mockImplementation((channel: string) => {
      if (channel === 'system/get-username') return Promise.resolve(null);
      if (channel === 'dialog/open-file') return Promise.reject(new Error('Dialog is unavailable'));
      return Promise.resolve(null);
    });
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    delete (window as typeof window & { electron?: unknown }).electron;
  });

  const renderModal = () =>
    render(
      <ThemeProvider>
        <ToasterProvider>
          <SubmitRenderModal isOpen onClose={() => {}} />
        </ToasterProvider>
      </ThemeProvider>,
    );

  it('surfaces dialog unavailability when browsing for a scene file', async () => {
    renderModal();

    const browseButtons = screen.getAllByRole('button', { name: /browse/i });
    await userEvent.click(browseButtons[0]);

    expect(await screen.findByText(/dialog is unavailable/i)).toBeInTheDocument();
  });
});
