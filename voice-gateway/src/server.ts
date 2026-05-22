import express from "express";
import http from "http";
import path from "path";
import { fileURLToPath } from "url";
import { WebSocketServer, type WebSocket } from "ws";
import { v4 as uuid } from "uuid";
import { gatewayBreakdown, wallMs } from "./latency.js";

const PORT = Number(process.env.PORT ?? process.env.VOICE_GATEWAY_PORT ?? 3000);
const BACKEND_URL = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";
const __dirname = path.dirname(fileURLToPath(import.meta.url));

type ClientState = {
  sessionId: string;
  patientId: string;
  patientName: string;
  phone: string;
  language: string;
};

const clients = new Map<WebSocket, ClientState>();

function send(ws: WebSocket, payload: object) {
  if (ws.readyState === ws.OPEN) {
    ws.send(JSON.stringify(payload));
  }
}

async function handleTurn(
  ws: WebSocket,
  text: string,
  clientTiming?: { stt_ms?: number; language?: string },
) {
  const state = clients.get(ws);
  if (!state) {
    send(ws, { type: "error", message: "Session not initialized. Refresh the page." });
    return;
  }

  const turnId = uuid();
  const receivedMs = wallMs();

  try {
    const res = await fetch(`${BACKEND_URL}/api/v1/agent/turn`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: state.sessionId,
        patient_id: state.patientId,
        patient_name: state.patientName,
        phone: state.phone,
        text,
        turn_id: turnId,
        language: clientTiming?.language ?? state.language,
      }),
    });

    const data = await res.json().catch(() => ({}));

    if (!res.ok) {
      const detail =
        typeof data.detail === "string"
          ? data.detail
          : JSON.stringify(data.detail ?? data);
      send(ws, {
        type: "agent_error",
        message: `Backend error (${res.status}): ${detail}. Is uvicorn running on port 8000?`,
      });
      return;
    }

    const agentDoneMs = wallMs();

    send(ws, {
      type: "agent_reply",
      reply: data.reply ?? "No reply from agent.",
      language: data.language ?? "en",
      trace: data.trace ?? [],
      turn_id: turnId,
      server_agent_ms: agentDoneMs - receivedMs,
    });

    send(ws, {
      type: "latency",
      ...gatewayBreakdown({
        turnId,
        receivedMs,
        agentDoneMs,
        replySentMs: wallMs(),
        clientSttMs: clientTiming?.stt_ms,
      }),
      server_latency: data.latency,
    });
  } catch (err) {
    send(ws, {
      type: "agent_error",
      message: `Cannot reach backend at ${BACKEND_URL}. Start: uvicorn app.main:app --reload --port 8000`,
      detail: String(err),
    });
  }
}

const publicDir = path.join(__dirname, "../public");
const indexHtml = path.join(publicDir, "index.html");

const app = express();
app.use(express.static(publicDir, { index: false, maxAge: 0 }));

app.get("/health", async (_req, res) => {
  let backendOk = false;
  try {
    const r = await fetch(`${BACKEND_URL}/health`, { signal: AbortSignal.timeout(2000) });
    backendOk = r.ok;
  } catch {
    backendOk = false;
  }
  res.json({
    status: "ok",
    ui: `http://127.0.0.1:${PORT}`,
    websocket: `ws://127.0.0.1:${PORT}`,
    backend: BACKEND_URL,
    backend_ok: backendOk,
  });
});

app.get("/", (_req, res) => {
  res.sendFile(indexHtml);
});

app.get("*", (req, res, next) => {
  if (req.path.startsWith("/health")) return next();
  res.sendFile(indexHtml);
});

const server = http.createServer(app);
const wss = new WebSocketServer({ server });

wss.on("connection", (ws) => {
  ws.on("message", async (raw) => {
    try {
      const msg = JSON.parse(raw.toString());

      if (msg.type === "init") {
        clients.set(ws, {
          sessionId: msg.session_id ?? uuid(),
          patientId: msg.patient_id ?? uuid(),
          patientName: msg.patient_name ?? "Guest",
          phone: msg.phone ?? "0000000000",
          language: msg.language ?? "en",
        });
        send(ws, { type: "ready", session_id: clients.get(ws)!.sessionId });
        return;
      }

      if (msg.type === "user_text") {
        if (!msg.text?.trim()) {
          send(ws, { type: "error", message: "Empty message — speak or type something first." });
          return;
        }
        await handleTurn(ws, msg.text.trim(), {
          stt_ms: typeof msg.client_stt_ms === "number" ? msg.client_stt_ms : 0,
          language: typeof msg.language === "string" ? msg.language : undefined,
        });
        return;
      }

      if (msg.type === "barge_in") {
        send(ws, { type: "interrupt_ack" });
        return;
      }

      if (msg.type === "outbound_start") {
        try {
          const res = await fetch(`${BACKEND_URL}/api/v1/sessions/outbound`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(msg.payload),
          });
          const data = await res.json().catch(() => ({}));
          if (!res.ok) {
            send(ws, {
              type: "agent_error",
              message: `Outbound failed (${res.status}): ${JSON.stringify(data.detail ?? data)}`,
            });
            return;
          }
          const state = clients.get(ws);
          if (state) state.sessionId = data.session_id;
          send(ws, {
            type: "outbound_ready",
            opening_prompt: data.opening_prompt,
            session_id: data.session_id,
          });
        } catch (err) {
          send(ws, {
            type: "agent_error",
            message: `Backend not reachable for outbound. Start uvicorn on port 8000.`,
            detail: String(err),
          });
        }
      }
    } catch (err) {
      send(ws, { type: "error", message: "Server error processing message.", detail: String(err) });
    }
  });

  ws.on("close", () => clients.delete(ws));
});

server.listen(PORT, () => {
  console.log(`Demo UI + WebSocket  http://127.0.0.1:${PORT}`);
  console.log(`Health check         http://127.0.0.1:${PORT}/health`);
  console.log(`Backend expected     ${BACKEND_URL}`);
});
