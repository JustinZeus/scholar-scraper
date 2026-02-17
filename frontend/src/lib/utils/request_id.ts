import { ApiRequestError } from "@/lib/api/errors";

export function toRequestId(value: unknown): string | null {
  if (value instanceof ApiRequestError) {
    return value.requestId;
  }
  return null;
}
