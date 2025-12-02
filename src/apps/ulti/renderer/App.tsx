import React, { useCallback, useEffect, useMemo, useState } from 'react';
import DiagnosticsScreen from './components/DiagnosticsScreen';
import FirstRunWizard from './components/FirstRunWizard';
import HomeScreen from './components/HomeScreen';
import LogsPanel from './components/LogsPanel';
import SettingsScreen from './components/SettingsScreen';
import TaskList from './components/TaskList';
import VersionFooter from './components/VersionFooter';
import AppShell from './components/layout/AppShell';
import ProjectSwitcher from './components/ProjectSwitcher';
import { ThemeProvider } from './styles/ThemeContext';
import { ToasterProvider } from './components/ui';

type DesktopConfig = {
  hasCompletedWizard: boolean;
  createdAt: string;
  updatedAt: string;
  profile?: 'vfx' | 'archviz' | 'freelancer' | 'demo';
  pythonPath?: string;
  projectRoot?: string;
  currentProject?: string;
  recentProjects?: { name: string; path: string; lastOpenedAt: string }[];
  quickActionPresets?: {
    [projectName: string]: {
      vendorIngest?: { sourcePath?: string };
      dccPublish?: { dccType?: string; lastScenePath?: string };
      renderSubmit?: { profileName?: string; lastFrameRange?: string };
      clientDelivery?: { playlistName?: string; targetPath?: string };
    };
  };
};

declare global {
  interface Window {
    electron: {
      invoke: <T = unknown>(channel: string, payload?: unknown) => Promise<T>;
    };
  }
}

type ProjectSelection = { name: string; path: string };

function App(): JSX.Element {
  const [config, setConfig] = useState<DesktopConfig | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [selectedTab, setSelectedTab] = useState<'home' | 'tasks' | 'logs' | 'diagnostics' | 'settings'>('home');
  const [currentProject, setCurrentProject] = useState<ProjectSelection | null>(null);

  const deriveCurrentProject = useCallback((nextConfig: DesktopConfig | null): ProjectSelection | null => {
    if (!nextConfig?.currentProject) {
      return null;
    }

    const match = nextConfig.recentProjects?.find((project) => project.path === nextConfig.currentProject);
    const nameFromPath = nextConfig.currentProject.split(/[\\/]/).pop() ?? nextConfig.currentProject;
    return { name: match?.name ?? nameFromPath, path: nextConfig.currentProject };
  }, []);

  const loadConfig = useCallback(async () => {
    try {
      const loadedConfig = await window.electron.invoke<DesktopConfig>('config/get');
      setConfig(loadedConfig);
      setCurrentProject(deriveCurrentProject(loadedConfig));
    } catch (error) {
      console.error('Failed to load desktop config', error);
    } finally {
      setLoading(false);
    }
  }, [deriveCurrentProject]);

  useEffect(() => {
    void loadConfig();
  }, [loadConfig]);

  const handleWizardComplete = useCallback(async () => {
    setLoading(true);
    await loadConfig();
  }, [loadConfig]);

  const handleRequestRerunWizard = useCallback(() => {
    setConfig((prev) => (prev ? { ...prev, hasCompletedWizard: false } : prev));
  }, []);

  const handleViewLogs = useCallback(() => {
    setSelectedTab('logs');
  }, []);

  const handleViewTasks = useCallback(() => {
    setSelectedTab('tasks');
  }, []);

  const handleProjectChange = useCallback(
    async (project: ProjectSelection | null) => {
      if (!config) {
        return;
      }

      const now = new Date().toISOString();
      const existingRecents = config.recentProjects ?? [];
      const updatedRecents = project
        ? [{ name: project.name, path: project.path, lastOpenedAt: now }, ...existingRecents.filter((p) => p.path !== project.path)]
        : existingRecents;

      try {
        const updatedConfig = await window.electron.invoke<DesktopConfig>('config/save', {
          currentProject: project?.path,
          recentProjects: updatedRecents,
        });

        setConfig(updatedConfig);
        setCurrentProject(project ?? deriveCurrentProject(updatedConfig));
      } catch (error) {
        console.error('Failed to update desktop config with project selection', error);
      }
    },
    [config, deriveCurrentProject],
  );

  const tabs = useMemo(
    () => [
      { id: 'home' as const, label: 'Home' },
      { id: 'tasks' as const, label: 'Tasks' },
      { id: 'logs' as const, label: 'Logs' },
      { id: 'diagnostics' as const, label: 'Diagnostics' },
      { id: 'settings' as const, label: 'Settings' },
    ],
    [],
  );

  return (
    <ThemeProvider>
      <ToasterProvider>
        {loading || !config ? (
          <div className="op-loading">Loading...</div>
        ) : !config.hasCompletedWizard ? (
          <AppShell showNav={false} headerSubtitle="Get set up in a few quick steps">
            <FirstRunWizard onComplete={() => void handleWizardComplete()} />
          </AppShell>
        ) : (
          <AppShell
            navItems={tabs.map((tab) => ({
              ...tab,
              onSelect: () => setSelectedTab(tab.id),
            }))}
            activeNavId={selectedTab}
            projectSwitcher={<ProjectSwitcher config={config} onProjectChange={handleProjectChange} />}
          >
            {selectedTab === 'home' && (
              <HomeScreen
                config={config}
                currentProject={currentProject ?? undefined}
                onViewTasks={handleViewTasks}
                onViewLogs={handleViewLogs}
              />
            )}
            {selectedTab === 'tasks' && <TaskList />}
            {selectedTab === 'logs' && <LogsPanel />}
            {selectedTab === 'diagnostics' && <DiagnosticsScreen />}
            {selectedTab === 'settings' && <SettingsScreen onRequestRerunWizard={handleRequestRerunWizard} />}
            <VersionFooter />
          </AppShell>
        )}
      </ToasterProvider>
    </ThemeProvider>
  );
}

export default App;
