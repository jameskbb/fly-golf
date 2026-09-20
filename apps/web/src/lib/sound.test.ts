import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { crossedImpact, initialSound, setSound, soundKey } from "./sound";
import { useStore } from "../store";

describe("when the strike fires", () => {
  const IMPACT = 2.5;

  it("fires on the frame that crosses impact, and only that frame", () => {
    expect(crossedImpact(2.46, 2.51, IMPACT)).toBe(true);
    expect(crossedImpact(2.51, 2.56, IMPACT)).toBe(false);
    expect(crossedImpact(2.3, 2.4, IMPACT)).toBe(false);
  });

  it("fires when a slow frame steps straight over impact", () => {
    expect(crossedImpact(2.1, 3.0, IMPACT)).toBe(true);
  });

  it("stays silent on the first frame of a playback (nothing to compare against)", () => {
    expect(crossedImpact(undefined, 2.6, IMPACT)).toBe(false);
  });

  it("stays silent for a shot that made no contact", () => {
    expect(crossedImpact(2.46, 2.51, IMPACT, false)).toBe(false);
  });

  it("re-arms instead of firing when the scrubber jumps backwards", () => {
    expect(crossedImpact(4.0, 1.0, IMPACT)).toBe(false); // the jump itself is silent
    expect(crossedImpact(1.0, 2.6, IMPACT)).toBe(true); // playing forward over it again does fire
  });

  it("fires exactly once over a run of frames", () => {
    let prev: number | undefined;
    let fired = 0;
    for (let t = 0; t <= 5; t += 1 / 60) {
      if (crossedImpact(prev, t, IMPACT)) fired++;
      prev = t;
    }
    expect(fired).toBe(1);
  });
});

describe("the sound preference", () => {
  // These tests run in node (vitest.config.ts), so stand up just enough browser to exercise the
  // remembered preference: localStorage, and no AudioContext (nothing should try to make a sound).
  const store = new Map<string, string>();
  const globals = globalThis as unknown as { window?: unknown };

  beforeEach(() => {
    store.clear();
    globals.window = {
      localStorage: {
        getItem: (k: string) => store.get(k) ?? null,
        setItem: (k: string, v: string) => void store.set(k, v),
      },
    };
    useStore.getState().set({ sound: true });
  });
  afterEach(() => {
    delete globals.window;
  });

  it("is on by default and remembered once turned off", () => {
    expect(initialSound()).toBe(true);
    setSound(false);
    expect(useStore.getState().sound).toBe(false);
    expect(initialSound()).toBe(false);
    setSound(true);
    expect(initialSound()).toBe(true);
  });

  it("survives a browser that refuses storage", () => {
    globals.window = {
      localStorage: {
        getItem: () => {
          throw new Error("blocked");
        },
        setItem: () => {
          throw new Error("blocked");
        },
      },
    };
    expect(initialSound()).toBe(true);
    expect(() => setSound(false)).not.toThrow();
    expect(useStore.getState().sound).toBe(false);
  });

  it("toggles on S and ignores every other key", () => {
    expect(soundKey({ key: "s" } as KeyboardEvent)).toBe(true);
    expect(useStore.getState().sound).toBe(false);
    expect(soundKey({ key: "S" } as KeyboardEvent)).toBe(true);
    expect(useStore.getState().sound).toBe(true);
    for (const k of ["b", "f", "r", "Escape", " "]) {
      expect(soundKey({ key: k } as KeyboardEvent)).toBe(false);
    }
    expect(useStore.getState().sound).toBe(true);
  });
});
