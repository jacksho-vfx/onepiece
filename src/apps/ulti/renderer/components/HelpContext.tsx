import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';

interface HelpContextValue {
  contextKey: string | null;
  setContextKey: (key: string | null) => void;
  registerContext: (id: string, key: string | null) => void;
  unregisterContext: (id: string) => void;
}

const HelpContext = createContext<HelpContextValue | undefined>(undefined);

let helpContextId = 0;

export function HelpContextProvider({ children }: { children: React.ReactNode }): JSX.Element {
  const [entries, setEntries] = useState<Array<{ id: string; key: string | null }>>([]);

  const registerContext = useCallback((id: string, key: string | null) => {
    setEntries((prev) => {
      const filtered = prev.filter((entry) => entry.id !== id);
      return [...filtered, { id, key }];
    });
  }, []);

  const unregisterContext = useCallback((id: string) => {
    setEntries((prev) => prev.filter((entry) => entry.id !== id));
  }, []);

  const contextKey = useMemo(() => {
    const latest = [...entries].reverse().find((entry) => entry.key);
    return latest?.key ?? null;
  }, [entries]);

  const value = useMemo(
    () => ({
      contextKey,
      setContextKey: (key: string | null) => registerContext('manual', key),
      registerContext,
      unregisterContext,
    }),
    [contextKey, registerContext, unregisterContext],
  );

  return <HelpContext.Provider value={value}>{children}</HelpContext.Provider>;
}

export function useHelpContext(key?: string | null): HelpContextValue {
  const context = useContext(HelpContext);
  const idRef = useRef<string>();

  if (!context) {
    throw new Error('useHelpContext must be used within a HelpContextProvider');
  }

  const { registerContext, unregisterContext } = context;

  if (!idRef.current) {
    helpContextId += 1;
    idRef.current = `help-context-${helpContextId}`;
  }

  useEffect(() => {
    if (typeof key === 'undefined') {
      return undefined;
    }

    registerContext(idRef.current as string, key ?? null);

    return () => {
      unregisterContext(idRef.current as string);
    };
  }, [key, registerContext, unregisterContext]);

  return context;
}
