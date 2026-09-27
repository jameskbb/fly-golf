import { describe, expect, it } from "vitest";
import { HOLE_THEMES } from "@fly-golf/protocol";
import { THEMES, themeFor } from "./theme";

describe("themeFor", () => {
  it("parkland for the practice green, an old hole without a theme, or an unknown theme", () => {
    expect(themeFor(null).id).toBe("parkland");
    expect(themeFor(undefined).id).toBe("parkland");
    expect(themeFor({}).id).toBe("parkland");
    expect(themeFor({ theme: "links" }).id).toBe("parkland");
    expect(themeFor({ theme: "toString" }).id).toBe("parkland");
  });
  it("dusk for back-nine holes", () => {
    expect(themeFor({ theme: "dusk" }).id).toBe("dusk");
  });
  it("has an entry for every theme the protocol names", () => {
    for (const id of HOLE_THEMES) expect(THEMES[id].id).toBe(id);
  });
  it("parkland keeps the renderer's original constants (the front nine must not change)", () => {
    const p = THEMES.parkland;
    expect(p.background).toBe("#a9c9e6");
    expect(p.sky).toMatchObject({ kind: "physical", sunPosition: [60, 40, 30], turbidity: 5, rayleigh: 1.1 });
    expect(p.sun).toEqual({ color: "#ffffff", intensity: 2.6, offset: [6, 10, 4], shadowBias: -0.0004 });
    expect(p.ground.rough).toEqual(["#2f6428", "#336c2b"]);
    expect(p.water.reflect).toBeUndefined();
    expect(p.trees.coniferShare).toBe(0.5);
  });
});
