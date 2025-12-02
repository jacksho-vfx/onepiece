import React from 'react';
import ProjectExplorer from './tools/ProjectExplorer';

type ProjectSelection = { name: string; path: string };

type ToolsScreenProps = {
  project?: ProjectSelection | null;
};

function ToolsScreen({ project }: ToolsScreenProps): JSX.Element {
  return (
    <div style={{ display: 'grid', gap: '1rem' }}>
      <ProjectExplorer project={project ?? null} />
    </div>
  );
}

export default ToolsScreen;
