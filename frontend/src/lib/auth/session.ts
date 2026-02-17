import { apiRequest } from "@/lib/api/client";

export interface SessionUser {
  id: number;
  email: string;
  is_admin: boolean;
  is_active: boolean;
}

export interface AuthSessionData {
  authenticated: boolean;
  csrf_token: string;
  user: SessionUser;
}

export interface MessageData {
  message: string;
}

export async function fetchMe() {
  return apiRequest<AuthSessionData>("/auth/me", { method: "GET" });
}

export async function loginSession(params: { email: string; password: string }) {
  return apiRequest<AuthSessionData>("/auth/login", {
    method: "POST",
    body: params,
  });
}

export async function logoutSession() {
  return apiRequest<MessageData>("/auth/logout", {
    method: "POST",
  });
}
