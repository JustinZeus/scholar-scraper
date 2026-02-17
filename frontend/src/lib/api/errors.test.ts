import { describe, expect, it } from "vitest";

import { ApiRequestError } from "@/lib/api/errors";

describe("ApiRequestError", () => {
  it("preserves structured metadata", () => {
    const error = new ApiRequestError({
      status: 409,
      code: "run_in_progress",
      message: "A run is already in progress",
      details: { run_id: 42 },
      requestId: "req_789",
    });

    expect(error.name).toBe("ApiRequestError");
    expect(error.status).toBe(409);
    expect(error.code).toBe("run_in_progress");
    expect(error.message).toBe("A run is already in progress");
    expect(error.details).toEqual({ run_id: 42 });
    expect(error.requestId).toBe("req_789");
  });
});
