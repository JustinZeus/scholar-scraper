/// <reference types="vite/client" />

declare module "@/theme/presets/*.js" {
  const value: Record<string, unknown>;
  export default value;
}
