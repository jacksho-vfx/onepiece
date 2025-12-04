import { contextBridge, ipcRenderer, type IpcRendererEvent } from 'electron';

const electronApi = {
  invoke: <T = unknown>(channel: string, payload?: unknown): Promise<T> =>
    ipcRenderer.invoke(channel, payload),
  on: (channel: string, listener: (event: IpcRendererEvent, ...args: unknown[]) => void): (() => void) => {
    const subscription = (event: IpcRendererEvent, ...args: unknown[]) => listener(event, ...args);
    ipcRenderer.on(channel, subscription);
    return () => ipcRenderer.removeListener(channel, subscription);
  },
};

contextBridge.exposeInMainWorld('electron', electronApi);

export type ElectronApi = typeof electronApi;
