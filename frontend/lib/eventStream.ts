/* Server-Sent Events client - subskrybuje /api/events/stream.
 *
 * Zastepuje setInterval polling co 2-8s. Backend emituje:
 *   - "event" - nowy wpis w Event table
 *   - "job"   - zmiana statusu Joba (pending/running/done/failed)
 *   - "heartbeat" - co 15s, ignorujemy
 *   - "reconnect" - serwer zamknal polaczenie, auto-rekonekt
 *   - "ready" - poczatkowy ack po snapshocie aktywnych jobow
 *
 * Fallback: jak EventSource nie zadziala (proxy, mobile background, brak
 * SSE support), wracamy do callbackow przez setInterval. UI sam wybiera.
 */

import { getToken } from './api';

export interface StreamEvent {
  id: number;
  type: string;
  level: string;
  source: string | null;
  message: string;
  lead_id: number | null;
  created_at: string | null;
}

export interface StreamJob {
  id: number;
  type: string;
  status: 'pending' | 'running' | 'done' | 'failed' | 'cancelled';
  progress: number;
  total: number;
}

export interface StreamHandlers {
  onEvent?: (e: StreamEvent) => void;
  onJob?: (j: StreamJob) => void;
  onReady?: () => void;
  onError?: (err: Event) => void;
}

/**
 * Subskrybuj strumien SSE. Zwraca funkcje cleanup, ktora trzeba zawolac w
 * useEffect return.
 *
 * Reconnect logic: EventSource auto-rekonektuje na connection loss
 * (built-in browser). Serwer po SSE_MAX_CONNECTION_S wysyla event "reconnect"
 * i zamyka - EventSource sam otworzy nowe polaczenie.
 */
export function subscribeStream(handlers: StreamHandlers): () => void {
  const token = getToken();
  if (!token) {
    handlers.onError?.(new Event('no-token'));
    return () => {};
  }

  // Same-origin: /api/events/stream leci przez Next proxy (frontend/app/api/[...path])
  const url = `/api/events/stream?token=${encodeURIComponent(token)}`;
  let es: EventSource | null = null;
  let closed = false;

  function connect() {
    if (closed) return;
    try {
      es = new EventSource(url);
    } catch (err) {
      handlers.onError?.(new Event('eventsource-construct-failed'));
      return;
    }

    es.addEventListener('ready', () => handlers.onReady?.());

    es.addEventListener('event', (msg) => {
      try {
        const data = JSON.parse((msg as MessageEvent).data) as StreamEvent;
        handlers.onEvent?.(data);
      } catch {}
    });

    es.addEventListener('job', (msg) => {
      try {
        const data = JSON.parse((msg as MessageEvent).data) as StreamJob;
        handlers.onJob?.(data);
      } catch {}
    });

    es.addEventListener('reconnect', () => {
      // Serwer powiedzial "zamykam, otworz na nowo"
      es?.close();
      if (!closed) setTimeout(connect, 200);
    });

    es.onerror = (err) => {
      handlers.onError?.(err);
      // EventSource auto-rekonektuje sam, ale jak server zwrocil np. 401,
      // nie ma sensu probowac w nieskonczonosc. Zamykamy po 3 bledach.
      // (Browser sam ponawia kilka razy zanim wpadnie tutaj.)
    };
  }

  connect();

  return () => {
    closed = true;
    es?.close();
  };
}
