import React, { useMemo, useState } from 'react';
import { designTokens } from '../styles/designTokens';

export interface DesktopConfig {
  hasCompletedWizard: boolean;
  createdAt: string;
  updatedAt: string;
  profile?: 'vfx' | 'archviz' | 'freelancer' | 'demo';
  pythonPath?: string;
  projectRoot?: string;
  currentProject?: string;
  recentProjects?: { name: string; path: string; lastOpenedAt: string }[];
}

interface ProjectSwitcherProps {
  config: DesktopConfig;
  onProjectChange: (project: { name: string; path: string } | null) => void;
}

declare global {
  interface Window {
    electron: {
      invoke: <T = unknown>(channel: string, payload?: unknown) => Promise<T>;
    };
  }
}

const BROWSE_VALUE = '__browse__';

function ProjectSwitcher({ config, onProjectChange }: ProjectSwitcherProps): JSX.Element {
  const [isBrowsing, setIsBrowsing] = useState(false);
  const recentProjects = config.recentProjects ?? [];

  const projectOptions = useMemo(() => {
    const options = [...recentProjects];

    if (config.currentProject && !options.some((project) => project.path === config.currentProject)) {
      const nameFromPath = config.currentProject.split(/[\\/]/).pop() ?? config.currentProject;
      options.unshift({ name: nameFromPath, path: config.currentProject, lastOpenedAt: new Date().toISOString() });
    }

    return options;
  }, [config.currentProject, recentProjects]);

  const handleSelect = async (value: string): Promise<void> => {
    if (value === BROWSE_VALUE) {
      setIsBrowsing(true);
      try {
        const path = await window.electron.invoke<string | null>('dialog/open-folder');
        if (path) {
          const name = path.split(/[\\/]/).pop() ?? path;
          onProjectChange({ name, path });
        }
      } finally {
        setIsBrowsing(false);
      }
      return;
    }

    if (!value) {
      onProjectChange(null);
      return;
    }

    const selected = projectOptions.find((project) => project.path === value);
    const nameFromPath = value.split(/[\\/]/).pop() ?? value;
    const project = selected ?? { name: nameFromPath, path: value, lastOpenedAt: new Date().toISOString() };
    onProjectChange({ name: project.name, path: project.path });
  };

  const selectedValue = config.currentProject ?? '';

  return (
    <div
      style={{
        display: 'grid',
        gap: '0.35rem',
        minWidth: '260px',
      }}
    >
      <label
        style={{
          display: 'grid',
          gap: '0.25rem',
          color: designTokens.colors.text,
          fontWeight: designTokens.typography.fontWeightMedium,
        }}
      >
        <span style={{ fontSize: designTokens.typography.fontSizeSm, color: designTokens.colors.textMuted }}>
          Project
        </span>
        <select
          value={selectedValue}
          onChange={(event) => void handleSelect(event.target.value)}
          style={{
            padding: `${designTokens.spacing.sm} ${designTokens.spacing.md}`,
            borderRadius: designTokens.radii.md,
            border: `1px solid ${designTokens.colors.border}`,
            background: designTokens.colors.surfaceAlt,
            color: designTokens.colors.text,
            fontWeight: designTokens.typography.fontWeightMedium,
            minWidth: '240px',
          }}
          disabled={isBrowsing}
        >
          <option value="">Select project…</option>
          {projectOptions.map((project) => (
            <option key={project.path} value={project.path}>
              {project.name}
            </option>
          ))}
          <option value={BROWSE_VALUE}>Browse…</option>
        </select>
      </label>
    </div>
  );
}

export default ProjectSwitcher;
