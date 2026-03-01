import { describe, expect, it } from "vitest";
import { ApiRequestError } from "@/lib/api/errors";
import { useRequestState } from "@/composables/useRequestState";

describe("useRequestState", () => {
  it("initializes with all values null", () => {
    const { errorMessage, errorRequestId, successMessage } = useRequestState();
    expect(errorMessage.value).toBeNull();
    expect(errorRequestId.value).toBeNull();
    expect(successMessage.value).toBeNull();
  });

  it("assignError extracts message and requestId from ApiRequestError", () => {
    const { errorMessage, errorRequestId, assignError } = useRequestState();
    assignError(
      new ApiRequestError({ status: 409, code: "conflict", message: "Conflict occurred", requestId: "req-42" }),
      "fallback",
    );
    expect(errorMessage.value).toBe("Conflict occurred");
    expect(errorRequestId.value).toBe("req-42");
  });

  it("assignError uses Error.message for generic errors", () => {
    const { errorMessage, errorRequestId, assignError } = useRequestState();
    assignError(new Error("something broke"), "fallback");
    expect(errorMessage.value).toBe("something broke");
    expect(errorRequestId.value).toBeNull();
  });

  it("assignError uses fallback for non-Error values", () => {
    const { errorMessage, assignError } = useRequestState();
    assignError("not an error object", "fallback text");
    expect(errorMessage.value).toBe("fallback text");
  });

  it("setSuccess sets the success message", () => {
    const { successMessage, setSuccess } = useRequestState();
    setSuccess("Operation completed");
    expect(successMessage.value).toBe("Operation completed");
  });

  it("clearAlerts resets all messages", () => {
    const { errorMessage, errorRequestId, successMessage, assignError, setSuccess, clearAlerts } = useRequestState();
    assignError(new ApiRequestError({ status: 500, code: "err", message: "fail", requestId: "r1" }), "fb");
    setSuccess("ok");
    clearAlerts();
    expect(errorMessage.value).toBeNull();
    expect(errorRequestId.value).toBeNull();
    expect(successMessage.value).toBeNull();
  });
});
