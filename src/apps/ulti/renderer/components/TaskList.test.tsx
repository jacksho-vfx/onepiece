/** @vitest-environment jsdom */

import '@testing-library/jest-dom/vitest';
import React from 'react';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import TaskList from './TaskList';

type Task = {
  id: string;
  label: string;
  command: string[];
  createdAt: string;
  startedAt?: string;
  finishedAt?: string;
  status: 'pending' | 'running' | 'succeeded' | 'failed';
};

const sampleTasks: Task[] = [
  {
    id: '1',
    label: 'Render submit',
    command: ['onepiece', 'render', 'submit', '--scene', '/scenes/shot01.ma', '--frames', '100-110'],
    createdAt: '2024-01-01T00:00:00.000Z',
    startedAt: '2024-01-01T00:00:00.000Z',
    finishedAt: '2024-01-01T00:05:00.000Z',
    status: 'succeeded',
  },
];

describe('TaskList render dashboard link', () => {
  const invokeMock = vi.fn();
  const onMock = vi.fn();

  beforeEach(() => {
    invokeMock.mockReset();
    onMock.mockReset();
    (window as typeof window & { electron?: unknown }).electron = {
      invoke: invokeMock,
      on: onMock,
    } as typeof window.electron;
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    delete (window as typeof window & { electron?: unknown }).electron;
  });

  it('opens the configured render dashboard URL', async () => {
    const configuredUrl = 'https://render.example.com/render';

    invokeMock.mockImplementation((channel: string) => {
      if (channel === 'render/dashboard-url') return Promise.resolve(configuredUrl);
      if (channel === 'tasks/list') return Promise.resolve(sampleTasks);
      if (channel === 'open-url') return Promise.resolve(undefined);
      return Promise.resolve(null);
    });
    onMock.mockImplementation(() => () => {});

    render(<TaskList />);

    const openButton = await screen.findByRole('button', { name: /open render dashboard/i });
    await waitFor(() => expect(openButton).toBeEnabled());

    await userEvent.click(openButton);

    expect(invokeMock).toHaveBeenCalledWith('open-url', { url: configuredUrl });
  });

  it('disables the link and surfaces an error when the URL is unavailable', async () => {
    invokeMock.mockImplementation((channel: string) => {
      if (channel === 'render/dashboard-url') return Promise.resolve(null);
      if (channel === 'tasks/list') return Promise.resolve(sampleTasks);
      return Promise.resolve(null);
    });
    onMock.mockImplementation(() => () => {});

    render(<TaskList />);

    const openButton = await screen.findByRole('button', { name: /open render dashboard/i });
    expect(openButton).toBeDisabled();

    expect(await screen.findByText('Render dashboard URL is not available.')).toBeInTheDocument();
  });
});
