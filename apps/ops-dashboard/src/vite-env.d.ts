/// <reference types="vite/client" />

declare global {
  interface Window {
    __OPS_UI_CONFIG__?: {
      missionControlBaseUrl?: string;
    };
  }
}

export {};

