import { v4 as uuid } from "uuid";
import { breakdown, nowMs, type TurnLatency } from "./latency.js";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";

export interface PipelineConfig {
  sessionId: string;
  patientId: string;
  patientName: string;
  phone: string;
  language?: string;
}

export interface PipelineResult {
  reply: string;
  language: string;
  trace: unknown[];
  latency: ReturnType<typeof breakdown>;
  clientLatency: TurnLatency;
}

/** Text-mode pipeline mirroring voice stages for measurable e2e latency. */
export async function runTextTurn(
  config: PipelineConfig,
  userText: string,
  options?: { speechEndMs?: number; bargeIn?: boolean }
): Promise<PipelineResult> {
  const turnId = uuid();
  const span: TurnLatency = { turnId };

  span.speechEndMs = options?.speechEndMs ?? nowMs();
  // STT: in browser this is Web Speech API final result timestamp
  span.sttDoneMs = nowMs();

  const agentRes = await fetch(`${BACKEND_URL}/api/v1/agent/turn`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      session_id: config.sessionId,
      patient_id: config.patientId,
      patient_name: config.patientName,
      phone: config.phone,
      text: userText,
      turn_id: turnId,
      latency: {
        speech_end_ms: span.speechEndMs,
        stt_done_ms: span.sttDoneMs,
      },
    }),
  });

  if (!agentRes.ok) {
    throw new Error(`Agent error: ${agentRes.status}`);
  }

  const data = (await agentRes.json()) as {
    reply: string;
    language: string;
    trace: unknown[];
    latency?: Record<string, unknown>;
  };

  span.agentDoneMs = nowMs();
  // TTS first byte: synthesize via browser speechSynthesis for demo
  await synthesizeSpeech(data.reply, data.language, options?.bargeIn);
  span.ttsFirstByteMs = nowMs();

  const clientBreakdown = breakdown(span);
  return {
    reply: data.reply,
    language: data.language,
    trace: data.trace,
    latency: clientBreakdown,
    clientLatency: span,
  };
}

function synthesizeSpeech(
  text: string,
  lang: string,
  bargeIn?: boolean
): Promise<void> {
  if (typeof globalThis.speechSynthesis === "undefined") {
    return Promise.resolve();
  }
  return new Promise((resolve) => {
    const utter = new SpeechSynthesisUtterance(text);
    const map: Record<string, string> = {
      en: "en-IN",
      hi: "hi-IN",
      ta: "ta-IN",
    };
    utter.lang = map[lang] ?? "en-IN";
    utter.rate = 1.05;
    if (bargeIn) {
      globalThis.speechSynthesis.cancel();
    }
    utter.onstart = () => resolve();
    utter.onerror = () => resolve();
    globalThis.speechSynthesis.speak(utter);
  });
}
