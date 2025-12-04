export type BrowserWindowLike = {
  webContents: {
    toggleDevTools: () => void;
  };
} | null;

export type MenuItemDefinition = {
  label?: string;
  role?: string;
  submenu?: MenuItemDefinition[];
  click?: () => void;
};

interface MenuTemplateOptions {
  allowDevTools: boolean;
  mainWindow?: BrowserWindowLike;
}

export function buildMenuTemplate({
  allowDevTools,
  mainWindow = null,
}: MenuTemplateOptions): MenuItemDefinition[] {
  const menuTemplate: MenuItemDefinition[] = [
    {
      label: 'File',
      submenu: [
        {
          role: 'quit',
          label: 'Quit',
        },
      ],
    },
  ];

  if (!allowDevTools) {
    return menuTemplate;
  }

  menuTemplate.push({
    label: 'View',
    submenu: [
      { role: 'reload', label: 'Reload' },
      { role: 'toggleDevTools', label: 'Toggle Developer Tools' },
    ],
  });

  menuTemplate.push({
    label: 'Developer',
    submenu: [
      {
        label: 'Toggle Dev Tools',
        click: () => mainWindow?.webContents.toggleDevTools(),
      },
    ],
  });

  return menuTemplate;
}
