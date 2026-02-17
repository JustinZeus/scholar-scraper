import type { ApiErrorPayload } from "@/lib/api/errors";

export interface ApiMeta {
  request_id: string | null;
}

export interface ApiSuccessEnvelope<T> {
  data: T;
  meta: ApiMeta;
}

export interface ApiErrorEnvelope {
  error: ApiErrorPayload;
  meta: ApiMeta;
}

export function isSuccessEnvelope<T>(value: unknown): value is ApiSuccessEnvelope<T> {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  return "data" in value && "meta" in value;
}

export function isErrorEnvelope(value: unknown): value is ApiErrorEnvelope {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  return "error" in value && "meta" in value;
}

export function readRequestId(payload: unknown): string | null {
  if (typeof payload !== "object" || payload === null) {
    return null;
  }
  const meta = (payload as { meta?: unknown }).meta;
  if (typeof meta !== "object" || meta === null) {
    return null;
  }
  const requestId = (meta as { request_id?: unknown }).request_id;
  if (typeof requestId !== "string" || !requestId.trim()) {
    return null;
  }
  return requestId;
}
