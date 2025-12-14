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
import ToolsScreen from './components/ToolsScreen';
import { ThemeProvider } from './styles/ThemeContext';
import { ToasterProvider, useToast } from './components/ui';
import { HelpContextProvider } from './components/HelpContext';

type StarterKitInstallResult = {
  status: 'installed' | 'skipped' | 'failed';
  profile: 'vfx' | 'archviz' | 'freelancer' | 'demo';
  target: string;
  message: string;
};

type DesktopConfig = {
  hasCompletedWizard: boolean;
  createdAt: string;
  updatedAt: string;
  justOnboarded?: boolean;
  profile?: 'vfx' | 'archviz' | 'freelancer' | 'demo';
  pythonPath?: string;
  projectRoot?: string;
  currentProject?: string;
  recentProjects?: { name: string; path: string; lastOpenedAt: string }[];
  quickActionPresets?: {
    [projectName: string]: {
      vendorIngest?: { sourcePath?: string };
      dccPublish?: { dccType?: string; lastScenePath?: string };
      renderSubmit?: {
        profileName?: string;
        lastFrameRange?: string;
        lastScenePath?: string;
        lastOutputPath?: string;
        farm?: string;
        dcc?: string;
        priority?: number;
        chunkSize?: number;
        optimize?: boolean;
        farmQueueDepth?: number;
        farmAverageFrameMs?: number;
        refreshCapabilities?: boolean;
        user?: string;
      };
      clientDelivery?: { playlistName?: string; targetPath?: string };
    };
  };
  awsSyncPresets?: {
    id: string;
    name: string;
    direction: 'from' | 'to' | 'download' | 'upload';
    localPath: string;
    bucketUrl: string;
    showCode?: string;
    remotePath?: string;
    remote?: string;
  }[];
  services?: {
    profiles: {
      key: string;
      name: string;
      description: string;
      args: string[];
      persistent?: boolean;
    }[];
    enabled?: Record<string, boolean>;
  };
};

type ProjectSelection = { name: string; path: string };

function StarterKitInstallListener(): JSX.Element {
  const { showToast } = useToast();

  useEffect(() => {
    const unsubscribe = window.electron.on(
      'starter-kit/install-result',
      (_event, payload: StarterKitInstallResult) => {
        if (!payload) {
          return;
        }

        if (payload.status === 'installed') {
          showToast({
            kind: 'success',
            message: 'Starter kit ready',
            description: `${payload.profile.toUpperCase()} files added to ${payload.target}`,
          });
          return;
        }

        const kind = payload.status === 'failed' ? 'error' : 'info';
        showToast({
          kind,
          message: 'Starter kit notice',
          description: payload.message,
        });
      },
    );

    return unsubscribe;
  }, [showToast]);

  return null;
}

function App(): JSX.Element {
  const [config, setConfig] = useState<DesktopConfig | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [selectedTab, setSelectedTab] = useState<
    'home' | 'tasks' | 'logs' | 'diagnostics' | 'tools' | 'settings'
  >('home');
  const [currentProject, setCurrentProject] = useState<ProjectSelection | null>(null);
  const [autoOpenIngestOnMount, setAutoOpenIngestOnMount] = useState(false);
  const [showEnvironmentReportPrompt, setShowEnvironmentReportPrompt] = useState(false);
  const [toolsFocus, setToolsFocus] = useState<'envProfile' | 'shotgrid' | 'pipelines' | 'perona' | null>(null);

  const deriveCurrentProject = useCallback((nextConfig: DesktopConfig | null): ProjectSelection | null => {
    if (!nextConfig?.currentProject) {
      return null;
    }

    const match = nextConfig.recentProjects?.find((project) => project.path === nextConfig.currentProject);
    const nameFromPath = nextConfig.currentProject.split(/[\\/]/).pop() ?? nextConfig.currentProject;
    return { name: match?.name ?? nameFromPath, path: nextConfig.currentProject };
  }, []);

  const loadConfig = useCallback(async (): Promise<DesktopConfig | null> => {
    try {
      const loadedConfig = await window.electron.invoke<DesktopConfig>('config/get');
      setConfig(loadedConfig);
      setCurrentProject(deriveCurrentProject(loadedConfig));
      return loadedConfig;
    } catch (error) {
      console.error('Failed to load main config', error);
      return null;
    } finally {
      setLoading(false);
    }
  }, [deriveCurrentProject]);

  useEffect(() => {
    void loadConfig();
  }, [loadConfig]);

  const handleWizardComplete = useCallback(async (options?: { openEnvironmentReport?: boolean }) => {
    setLoading(true);
    const loadedConfig = await loadConfig();

    if (loadedConfig && (loadedConfig.createdAt === loadedConfig.updatedAt || loadedConfig.justOnboarded)) {
      setAutoOpenIngestOnMount(true);
    }

    setShowEnvironmentReportPrompt(!options?.openEnvironmentReport);

    if (options?.openEnvironmentReport) {
      setSelectedTab('tools');
      setToolsFocus('envProfile');
    }
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

  const handleViewDiagnostics = useCallback(() => {
    setSelectedTab('diagnostics');
  }, []);

  const handleViewEnvironmentReport = useCallback(() => {
    setSelectedTab('tools');
    setToolsFocus('envProfile');
    setShowEnvironmentReportPrompt(false);
  }, []);

  const handleOpenShotgridOps = useCallback(() => {
    setSelectedTab('tools');
    setToolsFocus('shotgrid');
  }, []);

  const handleOpenPeronaTools = useCallback(() => {
    setSelectedTab('tools');
    setToolsFocus('perona');
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
        console.error('Failed to update main config with project selection', error);
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
      { id: 'tools' as const, label: 'Tools' },
      { id: 'settings' as const, label: 'Settings' },
    ],
    [],
  );

  const peronaConfigured = Boolean(config?.pythonPath || config?.projectRoot);

  return (
    <ThemeProvider>
      <HelpContextProvider>
        <ToasterProvider>
          <StarterKitInstallListener />
          {loading || !config ? (
            <div className="op-loading">Loading...</div>
          ) : !config.hasCompletedWizard ? (
              <AppShell showNav={false} headerSubtitle="Get set up in a few quick steps">
                <FirstRunWizard onComplete={(options) => void handleWizardComplete(options)} />
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
                  onSelectProject={handleProjectChange}
                  onViewTasks={handleViewTasks}
                  onViewLogs={handleViewLogs}
                  onViewDiagnostics={handleViewDiagnostics}
                  showEnvironmentReportPrompt={showEnvironmentReportPrompt}
                  onViewEnvironmentReport={handleViewEnvironmentReport}
                  onDismissEnvironmentReportPrompt={() => setShowEnvironmentReportPrompt(false)}
                  autoOpenIngestOnMount={autoOpenIngestOnMount}
                  onAutoOpenIngestHandled={() => setAutoOpenIngestOnMount(false)}
                  onOpenShotgridOps={handleOpenShotgridOps}
                  onOpenPeronaTools={handleOpenPeronaTools}
                  peronaConfigured={peronaConfigured}
                />
              )}
              {selectedTab === 'tasks' && <TaskList />}
              {selectedTab === 'logs' && <LogsPanel />}
              {selectedTab === 'diagnostics' && <DiagnosticsScreen />}
              {selectedTab === 'tools' && (
                <ToolsScreen
                  project={currentProject ?? undefined}
                  focusSection={toolsFocus}
                  onFocusHandled={() => setToolsFocus(null)}
                  onViewTasks={handleViewTasks}
                />
              )}
              {selectedTab === 'settings' && (
                <SettingsScreen
                  onRequestRerunWizard={handleRequestRerunWizard}
                  onConfigImported={loadConfig}
                />
              )}
              <VersionFooter />
            </AppShell>
          )}
        </ToasterProvider>
      </HelpContextProvider>
    </ThemeProvider>
  );
}

export default App;
