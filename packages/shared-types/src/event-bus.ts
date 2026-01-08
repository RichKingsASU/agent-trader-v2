export type EventEnvelope<TPayload extends Record<string, unknown> = Record<string, unknown>> = {
  event_type: string;
  agent_name: string;
  git_sha: string;
  ts: string;
  payload: TPayload;
  trace_id: string;
};

