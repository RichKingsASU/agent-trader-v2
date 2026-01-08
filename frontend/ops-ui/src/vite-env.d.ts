/// <reference types="vite/client" />

declare global {
  interface Window {
    __OPS_DASHBOARD_CONFIG__?: {
      basePath?: string;
      missionControlBaseUrl?: string;
      firebase?: {
        apiKey?: string;
        authDomain?: string;
        projectId?: string;
        storageBucket?: string;
        messagingSenderId?: string;
        appId?: string;
      };
    };
    __OPS_UI_CONFIG__?: {
      missionControlBaseUrl?: string;
    };
  }
}

export {};

