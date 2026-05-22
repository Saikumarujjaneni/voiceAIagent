/** Wall-clock ms — comparable across browser and Node when used only within each tier. */
export function wallMs(): number {
  return Date.now();
}

export interface GatewayLatency {
  turnId: string;
  receivedMs: number;
  agentDoneMs?: number;
  replySentMs?: number;
  clientSttMs?: number;
}

export function gatewayBreakdown(span: GatewayLatency) {
  const agent =
    span.agentDoneMs != null ? span.agentDoneMs - span.receivedMs : null;
  const gatewayTotal =
    span.replySentMs != null ? span.replySentMs - span.receivedMs : null;

  return {
    turn_id: span.turnId,
    stt_ms: span.clientSttMs != null ? Math.round(span.clientSttMs) : null,
    agent_ms: agent != null ? Math.round(agent) : null,
    gateway_total_ms: gatewayTotal != null ? Math.round(gatewayTotal) : null,
    target_ms: 450,
    note: "e2e_ms (speech end → first audio) is measured in the browser when TTS starts.",
  };
}

/** Client-side: speech end → first TTS byte */
export function clientE2eBreakdown(opts: {
  turnId: string;
  speechEndMs: number;
  ttsStartMs: number;
  sttMs: number;
  serverAgentMs: number | null;
}) {
  const e2e = opts.ttsStartMs - opts.speechEndMs;
  const ttsMs =
    opts.serverAgentMs != null
      ? Math.max(0, Math.round(e2e - opts.serverAgentMs))
      : null;

  return {
    turn_id: opts.turnId,
    e2e_ms: Math.round(e2e),
    stt_ms: Math.round(opts.sttMs),
    agent_ms: opts.serverAgentMs,
    tts_ms: ttsMs,
    within_target_450ms: e2e < 450,
    target_ms: 450,
  };
}
