import { setCsrfTokenProvider } from "@/lib/api/client";
import { useAuthStore } from "@/stores/auth";
import { useThemeStore } from "@/stores/theme";

export async function bootstrapAppProviders(): Promise<void> {
  const theme = useThemeStore();
  theme.initialize();

  const auth = useAuthStore();
  setCsrfTokenProvider(() => auth.csrfToken);
  await auth.bootstrapSession();
}
