import React, { useEffect, useRef } from 'react';
import ProjectExplorer from './tools/ProjectExplorer';
import EnvProfileTool from './tools/EnvProfileTool';
import DccShotLauncher, { type ShotReference } from './tools/DccShotLauncher';
import { Card, SectionHeader } from './ui';
import AnimationToolsPanel from './tools/AnimationToolsPanel';
import AwsSyncTool from './tools/AwsSyncTool';

type ProjectSelection = { name: string; path: string };

type ToolsScreenProps = {
  project?: ProjectSelection | null;
  focusSection?: 'envProfile' | null;
  onFocusHandled?: () => void;
  shots?: ShotReference[];
};

function ToolsScreen({ project, focusSection, onFocusHandled, shots }: ToolsScreenProps): JSX.Element {
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

      <SectionHeader
        title="Animation tools"
        subtitle="Debug animation scenes, clean them up, and trigger playblasts."
      />
      <AnimationToolsPanel />

      <SectionHeader title="Project Tools" subtitle="Inspect and manage your project files." />
      <div
        style={{
          display: 'grid',
          gap: '1rem',
          gridTemplateColumns: 'repeat(auto-fit, minmax(360px, 1fr))',
        }}
      >
        <Card>
          <SectionHeader
            title="Open shot in DCC"
            subtitle="Use OnePiece to launch scenes in the right DCC."
          />
          <DccShotLauncher project={project ?? null} shots={shots} />
        </Card>

        <ProjectExplorer project={project ?? null} />

        <AwsSyncTool />
      </div>
    </div>
  );
}

export default ToolsScreen;
