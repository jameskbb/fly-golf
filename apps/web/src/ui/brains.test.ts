import { describe, expect, it } from "vitest";
import { LOOKS } from "../scene/looks";
import { BRAINS, personaFor } from "./brains";

describe("brain personas", () => {
  it("gives every brain its own 3D model", () => {
    const ids = BRAINS.map((b) => b.persona.id);
    expect(new Set(ids).size).toBe(BRAINS.length);
    for (const id of ids) expect(LOOKS[id]).toBeDefined();
  });

  it("keeps the untrained connectome on the unchanged baseline fly", () => {
    expect(personaFor({ id: "malecns", is_mock: false })).toBe("fly");
    const fly = LOOKS.fly;
    expect(fly.materials).toEqual({});
    expect([fly.thigh, fly.foot]).toEqual([1, 1]);
    expect([fly.head, fly.thorax, fly.abdomen, fly.grip]).toEqual([
      undefined,
      undefined,
      undefined,
      undefined,
    ]);
    expect(fly.bag).toEqual({ body: "#b2261e", rim: "#1c1c1c", band: "#f4f1ea" });
  });

  it("dresses the trained readout as the golfer", () => {
    expect(personaFor({ id: "malecns-trained", is_mock: false })).toBe("golfer");
  });

  it("never gives a mock controller a real fly's body", () => {
    expect(personaFor({ id: "mock", is_mock: true })).toBe("windup");
    expect(personaFor({ id: "some-future-mock", is_mock: true })).toBe("windup");
    expect(personaFor({ id: "some-future-brain", is_mock: false })).toBe("fly");
  });
});
