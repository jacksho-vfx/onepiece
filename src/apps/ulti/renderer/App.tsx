import React, { useCallback, useEffect, useState } from 'react';
import FirstRunWizard from './components/FirstRunWizard';
import HomeScreen from './components/HomeScreen';

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

  if (loading || !config) {
    return <div className="op-loading">Loading...</div>;
  }

  if (!config.hasCompletedWizard) {
    return <FirstRunWizard onComplete={() => void handleWizardComplete()} />;
  }

  return <HomeScreen config={config} />;
}

export default App;
