import { Envelope, ErrorData, PROTOCOL_VERSION } from "@fly-golf/protocol";

export interface SimulationHandlers {
  onReady: () => void;
  onMessage: (msg: Envelope) => void;
  onMismatch: (message: string) => void;
  onClosed: () => void;
}

/** Connect to WS /ws/simulation, perform the versioned hello, and reconnect on drop. */
export function connectSimulation(h: SimulationHandlers): () => void {
  let ws: WebSocket | null = null;
  let stopped = false;
  let retry: number | undefined;

  const open = () => {
    const scheme = location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(`${scheme}://${location.host}/ws/simulation`);
    ws.onopen = () => {
      ws?.send(
        JSON.stringify({
          type: "hello",
          protocol_version: PROTOCOL_VERSION,
          seq: 0,
          data: { client: "fly-golf-web", protocol_version: PROTOCOL_VERSION },
        }),
      );
    };
    ws.onmessage = (ev) => {
      let msg: Envelope;
      try {
        msg = Envelope.parse(JSON.parse(ev.data));
      } catch {
        return; // never act on malformed messages
      }
      if (msg.type === "hello") {
        if (msg.protocol_version !== PROTOCOL_VERSION) {
          stopped = true;
          h.onMismatch(
            `Backend speaks protocol v${msg.protocol_version}; this page speaks v${PROTOCOL_VERSION}.`,
          );
          ws?.close();
        } else h.onReady();
        return;
      }
      if (msg.type === "error") {
        const e = ErrorData.safeParse(msg.data);
        if (e.success && e.data.code === "protocol_mismatch") {
          stopped = true;
          h.onMismatch(e.data.message);
          return;
        }
      }
      h.onMessage(msg);
    };
    ws.onclose = () => {
      h.onClosed();
      if (!stopped) retry = window.setTimeout(open, 1500);
    };
  };
  open();
  return () => {
    stopped = true;
    if (retry) window.clearTimeout(retry);
    ws?.close();
  };
}
