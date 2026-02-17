import { createApp } from "vue";
import { createPinia } from "pinia";

import AppShell from "@/app/AppShell.vue";
import router from "@/app/router";
import { bootstrapAppProviders } from "@/app/providers";
import "@/styles.css";

async function main(): Promise<void> {
  const app = createApp(AppShell);
  const pinia = createPinia();

  app.use(pinia);
  await bootstrapAppProviders();

  app.use(router);
  await router.isReady();

  app.mount("#app");
}

void main();
