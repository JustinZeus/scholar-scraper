import { apiRequest } from "@/lib/api/client";

export interface CsrfBootstrapData {
  csrf_token: string;
  authenticated: boolean;
}

export async function fetchCsrfBootstrap() {
  return apiRequest<CsrfBootstrapData>("/auth/csrf", { method: "GET" });
}
