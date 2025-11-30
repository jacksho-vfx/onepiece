import React, { useCallback, useEffect, useMemo, useState } from 'react';
import DiagnosticsScreen from './components/DiagnosticsScreen';
import FirstRunWizard from './components/FirstRunWizard';
import HomeScreen from './components/HomeScreen';
import LogsPanel from './components/LogsPanel';
import SettingsScreen from './components/SettingsScreen';
import VersionFooter from './components/VersionFooter';

type DesktopConfig = {
  hasCompletedWizard: boolean;
  createdAt: string;
  updatedAt: string;
  profile?: 'vfx' | 'archviz' | 'freelancer' | 'demo';
  pythonPath?: string;
  projectRoot?: string;
};

declare global {
  interface Window {
    electron: {
      invoke: <T = unknown>(channel: string, payload?: unknown) => Promise<T>;
    };
  }
}

function App(): JSX.Element {
  const [config, setConfig] = useState<DesktopConfig | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [selectedTab, setSelectedTab] = useState<'home' | 'logs' | 'diagnostics' | 'settings'>('home');

  const loadConfig = useCallback(async () => {
    try {
      const loadedConfig = await window.electron.invoke<DesktopConfig>('config/get');
      setConfig(loadedConfig);
    } catch (error) {
      console.error('Failed to load desktop config', error);
    } finally {
      setLoading(false);
    }
  }, []);

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

  const tabs = useMemo(
    () => [
      { id: 'home' as const, label: 'Home' },
      { id: 'logs' as const, label: 'Logs' },
      { id: 'diagnostics' as const, label: 'Diagnostics' },
      { id: 'settings' as const, label: 'Settings' },
    ],
    [],
  );

  if (loading || !config) {
    return <div className="op-loading">Loading...</div>;
  }

  if (!config.hasCompletedWizard) {
    return <FirstRunWizard onComplete={() => void handleWizardComplete()} />;
  }

  return (
    <div className="op-app">
      <nav className="op-nav">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            type="button"
            className={tab.id === selectedTab ? 'op-nav__item is-active' : 'op-nav__item'}
            onClick={() => setSelectedTab(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </nav>
      <main className="op-content">
        {selectedTab === 'home' && <HomeScreen config={config} />}
        {selectedTab === 'logs' && <LogsPanel />}
        {selectedTab === 'diagnostics' && <DiagnosticsScreen />}
        {selectedTab === 'settings' && <SettingsScreen onRequestRerunWizard={handleRequestRerunWizard} />}
      </main>
      <VersionFooter />
    </div>
  );
}

export default App;
