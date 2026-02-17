import { defineStore } from "pinia";

export interface GlobalErrorState {
  message: string;
  requestId: string | null;
}

export const useUiStore = defineStore("ui", {
  state: () => ({
    globalError: null as GlobalErrorState | null,
  }),
  actions: {
    setGlobalError(error: GlobalErrorState): void {
      this.globalError = error;
    },
    clearGlobalError(): void {
      this.globalError = null;
    },
  },
});
