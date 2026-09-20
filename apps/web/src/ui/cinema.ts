import { useStore } from "../store";

/** Cinema mode: the 3D course fills the window and every panel, card and button is hidden.
 *  F toggles it (and the browser's own fullscreen, where allowed); Esc leaves it. A page opened
 *  with `?cinema=1` starts in it without asking for browser fullscreen, which is how the social
 *  clips are recorded (social/short-01/tools/capture.mjs). */

/** `?cinema=1` (or `true` / `yes` / an empty value) asks for cinema mode on load. */
export function cinemaFromSearch(search: string): boolean {
  const v = new URLSearchParams(search).get("cinema");
  return v !== null && ["", "1", "true", "yes", "on"].includes(v.toLowerCase());
}

export function initialCinema(): boolean {
  return typeof window !== "undefined" && cinemaFromSearch(window.location.search);
}

export function setCinema(on: boolean) {
  const st = useStore.getState();
  if (st.cinema === on) return;
  st.set({ cinema: on, cinemaHintAt: on ? Date.now() : undefined });
  const doc = typeof document !== "undefined" ? document : undefined;
  if (!doc) return;
  try {
    if (on && doc.fullscreenEnabled && !doc.fullscreenElement) {
      void doc.documentElement.requestFullscreen().catch(() => {});
    } else if (!on && doc.fullscreenElement) {
      void doc.exitFullscreen().catch(() => {});
    }
  } catch {
    // Browser fullscreen is a nicety; cinema mode works without it.
  }
}

export const toggleCinema = () => setCinema(!useStore.getState().cinema);

let watching = false;
/** Leaving the browser's fullscreen (its own Esc handling) also leaves cinema mode. */
export function watchFullscreenExit() {
  if (watching || typeof document === "undefined") return;
  watching = true;
  document.addEventListener("fullscreenchange", () => {
    if (!document.fullscreenElement && useStore.getState().cinemaHintAt) setCinema(false);
  });
}

/** Handles F and Esc for cinema mode; returns true when it consumed the key. */
export function cinemaKey(e: KeyboardEvent): boolean {
  if (e.key === "f" || e.key === "F") {
    toggleCinema();
    return true;
  }
  if (e.key === "Escape" && useStore.getState().cinema) {
    setCinema(false);
    return true;
  }
  return false;
}
