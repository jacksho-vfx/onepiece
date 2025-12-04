import React, { useEffect, useRef } from 'react';
import ProjectExplorer from './tools/ProjectExplorer';
import EnvProfileTool from './tools/EnvProfileTool';
import DccShotLauncher, { type ShotReference } from './tools/DccShotLauncher';
import { Card, SectionHeader } from './ui';
import AnimationToolsPanel from './tools/AnimationToolsPanel';
import AwsSyncTool from './tools/AwsSyncTool';
import DeliveryPanel from './tools/DeliveryPanel';
import PeronaPanel from './tools/PeronaPanel';
import PipelineRunnerPanel from './tools/PipelineRunnerPanel';
import ChopperPlayground from './tools/ChopperPlayground';
import UnrealImportTool from './tools/UnrealImportTool';

type ProjectSelection = { name: string; path: string };

type ToolsScreenProps = {
  project?: ProjectSelection | null;
  focusSection?: 'envProfile' | 'shotgrid' | 'pipelines' | 'perona' | null;
  onFocusHandled?: () => void;
  shots?: ShotReference[];
  onViewTasks?: () => void;
};

function ToolsScreen({ project, focusSection, onFocusHandled, shots, onViewTasks }: ToolsScreenProps): JSX.Element {
  const envProfileRef = useRef<HTMLDivElement | null>(null);
  const shotgridRef = useRef<HTMLDivElement | null>(null);
  const pipelinesRef = useRef<HTMLDivElement | null>(null);
  const peronaRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (focusSection === 'envProfile' && envProfileRef.current) {
      envProfileRef.current.scrollIntoView({ behavior: 'smooth', block: 'start' });
      onFocusHandled?.();
    }
    if (focusSection === 'shotgrid' && shotgridRef.current) {
      shotgridRef.current.scrollIntoView({ behavior: 'smooth', block: 'start' });
      onFocusHandled?.();
    }
    if (focusSection === 'pipelines' && pipelinesRef.current) {
      pipelinesRef.current.scrollIntoView({ behavior: 'smooth', block: 'start' });
      onFocusHandled?.();
    }
    if (focusSection === 'perona' && peronaRef.current) {
      peronaRef.current.scrollIntoView({ behavior: 'smooth', block: 'start' });
      onFocusHandled?.();
    }
  }, [focusSection, onFocusHandled]);

  return (
    <div style={{ display: 'grid', gap: '1rem' }}>
      <div ref={envProfileRef}>
        <EnvProfileTool />
      </div>

      <div ref={pipelinesRef}>
        <SectionHeader
          title="Pipelines"
          subtitle="List Trafalgar pipelines and trigger runs with parameters."
        />
        <PipelineRunnerPanel onViewTasks={onViewTasks} />
      </div>

      <div ref={peronaRef}>
        <SectionHeader
          title="Perona"
          subtitle="Start the Perona dashboard and review cost recommendations."
        />
        <PeronaPanel project={project ?? null} />
      </div>

      <SectionHeader
        title="Animation tools"
        subtitle="Debug animation scenes, clean them up, and trigger playblasts."
      />
      <AnimationToolsPanel />

      <SectionHeader
        title="Unreal Import"
        subtitle="Rehydrate published packages into Unreal, with dry-run previews."
      />
      <UnrealImportTool project={project ?? null} />

      <SectionHeader
        title="ShotGrid & Delivery"
        subtitle="Package playlists, seed new shows, and deliver approved Versions without leaving the desktop."
      />
      <div ref={shotgridRef}>
        <DeliveryPanel />
      </div>

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

        <ChopperPlayground />
      </div>
    </div>
  );
}

export default ToolsScreen;
