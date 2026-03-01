import { ref } from "vue";
import { ApiRequestError } from "@/lib/api/errors";

export function useRequestState() {
  const errorMessage = ref<string | null>(null);
  const errorRequestId = ref<string | null>(null);
  const successMessage = ref<string | null>(null);

  function clearAlerts(): void {
    errorMessage.value = null;
    errorRequestId.value = null;
    successMessage.value = null;
  }

  function assignError(error: unknown, fallback: string): void {
    if (error instanceof ApiRequestError) {
      errorMessage.value = error.message;
      errorRequestId.value = error.requestId;
      return;
    }
    if (error instanceof Error && error.message) {
      errorMessage.value = error.message;
      return;
    }
    errorMessage.value = fallback;
  }

  function setSuccess(message: string): void {
    successMessage.value = message;
  }

  return {
    errorMessage,
    errorRequestId,
    successMessage,
    clearAlerts,
    assignError,
    setSuccess,
  };
}
