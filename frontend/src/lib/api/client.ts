import {
  isErrorEnvelope,
  isSuccessEnvelope,
  readRequestId,
  type ApiSuccessEnvelope,
} from "@/lib/api/envelope";
import { ApiRequestError } from "@/lib/api/errors";

export type HttpMethod = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

export interface ApiRequestOptions {
  method?: HttpMethod;
  body?: unknown | FormData;
  headers?: Record<string, string>;
}

const UNSAFE_METHODS = new Set<HttpMethod>(["POST", "PUT", "PATCH", "DELETE"]);
const API_BASE = "/api/v1";

let csrfTokenProvider: (() => string | null) | null = null;

export function setCsrfTokenProvider(provider: () => string | null): void {
  csrfTokenProvider = provider;
}

export async function apiRequest<T>(path: string, options: ApiRequestOptions = {}): Promise<ApiSuccessEnvelope<T>> {
  const method = options.method ?? "GET";
  const headers = new Headers(options.headers ?? {});
  headers.set("Accept", "application/json");

  const hasBody = options.body !== undefined;
  const isFormData = typeof FormData !== "undefined" && options.body instanceof FormData;
  let requestBody: BodyInit | undefined;

  if (hasBody && !isFormData && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  if (hasBody) {
    requestBody = isFormData ? (options.body as FormData) : JSON.stringify(options.body);
  }

  if (UNSAFE_METHODS.has(method) && csrfTokenProvider) {
    const csrfToken = csrfTokenProvider();
    if (csrfToken) {
      headers.set("X-CSRF-Token", csrfToken);
    }
  }

  const response = await fetch(`${API_BASE}${path}`, {
    method,
    headers,
    credentials: "include",
    body: requestBody,
  });

  const raw = await parseResponseBody(response);
  const requestId = readRequestId(raw) ?? response.headers.get("X-Request-ID");

  if (!response.ok) {
    if (isErrorEnvelope(raw)) {
      throw new ApiRequestError({
        status: response.status,
        code: raw.error.code || "error",
        message: raw.error.message || "Request failed.",
        details: raw.error.details,
        requestId,
      });
    }

    throw new ApiRequestError({
      status: response.status,
      code: "http_error",
      message: `Request failed with status ${response.status}.`,
      requestId,
    });
  }

  if (!isSuccessEnvelope<T>(raw)) {
    throw new ApiRequestError({
      status: response.status,
      code: "invalid_envelope",
      message: "Server returned an unexpected response format.",
      requestId,
      details: raw,
    });
  }

  return raw;
}

async function parseResponseBody(response: Response): Promise<unknown> {
  const contentType = response.headers.get("Content-Type") || "";
  if (!contentType.includes("application/json")) {
    return null;
  }
  try {
    return await response.json();
  } catch (_err) {
    return null;
  }
}
