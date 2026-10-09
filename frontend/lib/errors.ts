/** Typed error for every non-2xx response and for transport failures. */
export class ApiError extends Error {
  readonly code: string;
  readonly retryable: boolean;
  readonly requestId: string | null;
  readonly status: number;

  constructor(
    message: string,
    opts: { code: string; retryable: boolean; requestId: string | null; status: number },
  ) {
    super(message);
    this.name = 'ApiError';
    this.code = opts.code;
    this.retryable = opts.retryable;
    this.requestId = opts.requestId;
    this.status = opts.status;
  }
}