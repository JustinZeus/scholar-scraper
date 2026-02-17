import { describe, expect, it } from "vitest";

import {
  isErrorEnvelope,
  isSuccessEnvelope,
  readRequestId,
  type ApiSuccessEnvelope,
} from "@/lib/api/envelope";

describe("api envelope helpers", () => {
  it("recognizes a success envelope", () => {
    const payload: ApiSuccessEnvelope<{ ok: boolean }> = {
      data: { ok: true },
      meta: { request_id: "req_123" },
    };

    expect(isSuccessEnvelope(payload)).toBe(true);
    expect(isErrorEnvelope(payload)).toBe(false);
    expect(readRequestId(payload)).toBe("req_123");
  });

  it("recognizes an error envelope", () => {
    const payload = {
      error: {
        code: "invalid",
        message: "Invalid request",
        details: null,
      },
      meta: { request_id: "req_456" },
    };

    expect(isErrorEnvelope(payload)).toBe(true);
    expect(isSuccessEnvelope(payload)).toBe(false);
    expect(readRequestId(payload)).toBe("req_456");
  });

  it("returns null when request id is missing or invalid", () => {
    expect(readRequestId(null)).toBeNull();
    expect(readRequestId({})).toBeNull();
    expect(readRequestId({ meta: {} })).toBeNull();
    expect(readRequestId({ meta: { request_id: "" } })).toBeNull();
  });
});
