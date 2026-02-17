export interface ApiErrorPayload {
  code: string;
  message: string;
  details: unknown;
}

export class ApiRequestError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: unknown;
  readonly requestId: string | null;

  constructor(params: {
    status: number;
    code: string;
    message: string;
    details?: unknown;
    requestId?: string | null;
  }) {
    super(params.message);
    this.name = "ApiRequestError";
    this.status = params.status;
    this.code = params.code;
    this.details = params.details ?? null;
    this.requestId = params.requestId ?? null;
  }
}
