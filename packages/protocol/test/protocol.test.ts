import { readFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { Envelope, ErrorData, PROTOCOL_VERSION, ServerHello, ShotRecord, ClientHello } from "../src";

const here = dirname(fileURLToPath(import.meta.url));
const fixturesDir = join(here, "..", "fixtures");
const fixtures = readdirSync(fixturesDir).filter((f) => f.endsWith(".json"));

describe("protocol version", () => {
  it("matches the backend PROTOCOL_VERSION", () => {
    const py = readFileSync(join(here, "../../../services/sim/src/fly_golf/__init__.py"), "utf8");
    const m = py.match(/^PROTOCOL_VERSION\s*=\s*(\d+)/m);
    expect(m).not.toBeNull();
    expect(Number(m![1])).toBe(PROTOCOL_VERSION);
  });
});

describe("shared fixtures", () => {
  it("exist", () => {
    expect(fixtures.length).toBeGreaterThanOrEqual(4);
  });
  for (const name of fixtures) {
    it(`${name} validates`, () => {
      const msg = Envelope.parse(JSON.parse(readFileSync(join(fixturesDir, name), "utf8")));
      expect(msg.protocol_version).toBe(PROTOCOL_VERSION);
      if (msg.type === "hello") {
        const d = msg.data as Record<string, unknown>;
        if ("server" in d) ServerHello.parse(d);
        else ClientHello.parse(d);
      }
      if (msg.type === "error") ErrorData.parse(msg.data);
      if (msg.type === "shot_result") ShotRecord.parse(msg.data);
    });
  }
});

describe("validation rejects bad data", () => {
  it("rejects out-of-range motor channels in a shot record", () => {
    const raw = JSON.parse(readFileSync(join(fixturesDir, "shot_result.json"), "utf8"));
    raw.data.motor.channels.stroke_power = 1.7;
    expect(() => ShotRecord.parse(raw.data)).toThrow();
  });
  it("rejects unknown message types", () => {
    expect(() => Envelope.parse({ type: "teleport", protocol_version: 1, seq: 0, data: {} })).toThrow();
  });
});
