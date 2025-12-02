import React, { useEffect, useRef } from 'react';
import ProjectExplorer from './tools/ProjectExplorer';
import EnvProfileTool from './tools/EnvProfileTool';
import { SectionHeader } from './ui';

type ProjectSelection = { name: string; path: string };

type ToolsScreenProps = {
  project?: ProjectSelection | null;
  focusSection?: 'envProfile' | null;
  onFocusHandled?: () => void;
};

function ToolsScreen({ project, focusSection, onFocusHandled }: ToolsScreenProps): JSX.Element {
  const envProfileRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (focusSection === 'envProfile' && envProfileRef.current) {
      envProfileRef.current.scrollIntoView({ behavior: 'smooth', block: 'start' });
      onFocusHandled?.();
    }
  }, [focusSection, onFocusHandled]);

  return (
    <div style={{ display: 'grid', gap: '1rem' }}>
      <div ref={envProfileRef}>
        <SectionHeader
          title="Environment & Profile"
          subtitle="Validate your CLI setup and profile resolution from the desktop."
        />
        <EnvProfileTool />
      </div>

      <SectionHeader title="Project Tools" subtitle="Inspect and manage your project files." />
      <ProjectExplorer project={project ?? null} />
    </div>
  );
}

export default ToolsScreen;
