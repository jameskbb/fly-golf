import { describe, expect, it } from "vitest";
import { buildTimeline, lerpAngle, poseAt } from "./swing";
import { sampleTrajectory, toThree } from "./coords";

const stroke = { power: 0.6, backswing_s: 0.6, downswing_s: 0.24, contact: true };

describe("swing timeline", () => {
  const tl = buildTimeline(stroke, 3.0, false);

  it("orders beats", () => {
    expect(tl.aim0).toBeLessThan(tl.back0);
    expect(tl.back0).toBeLessThan(tl.down0);
    expect(tl.down0).toBeLessThan(tl.impact);
    expect(tl.end).toBeGreaterThan(tl.rollEnd);
  });

  it("club is at address before the swing and returns to the ball at impact", () => {
    expect(poseAt(tl, 0).club).toBe(0);
    expect(poseAt(tl, tl.down0).club).toBeCloseTo(tl.amplitude, 5);
    expect(poseAt(tl, tl.impact).club).toBeCloseTo(0, 5);
  });

  it("ball waits for impact, then follows the trajectory clock", () => {
    expect(poseAt(tl, tl.impact - 0.01).ballTime).toBeNull();
    expect(poseAt(tl, tl.impact + 1).ballTime).toBeCloseTo(1, 5);
    expect(poseAt(tl, tl.end + 5).ballTime).toBe(3.0);
    expect(poseAt(tl, tl.end + 5).phase).toBe("done");
  });

  it("more power means a longer backswing arc", () => {
    const weak = buildTimeline({ ...stroke, power: 0.1 }, 1, false);
    const strong = buildTimeline({ ...stroke, power: 0.9 }, 1, false);
    expect(strong.amplitude).toBeGreaterThan(weak.amplitude);
  });

  it("a whiff never moves the ball", () => {
    const whiff = buildTimeline({ ...stroke, contact: false }, 0, false);
    expect(poseAt(whiff, whiff.impact + 0.5).ballTime).toBeNull();
  });
});

describe("full swing on the course", () => {
  const iron = { ...stroke, club: { kind: "iron" }, swing_fraction: 0.9 };
  const tl = buildTimeline(iron, 6.0, false, { select: true });

  it("starts by pulling the chosen club from the bag", () => {
    expect(poseAt(tl, 0.1).phase).toBe("select");
    expect(poseAt(tl, 0.1).selectProgress).toBeLessThan(1);
    expect(poseAt(tl, tl.aim0).selectProgress).toBe(1);
    expect(poseAt(tl, tl.aim0 - 0.1).phase).toBe("address");
  });

  it("swings much further back than a putt and follows through", () => {
    const putt = buildTimeline(stroke, 3.0, false);
    expect(tl.full).toBe(true);
    expect(tl.amplitude).toBeGreaterThan(2 * putt.amplitude);
    expect(poseAt(tl, tl.followEnd - 0.01).club).toBeLessThan(-1);
    expect(poseAt(tl, tl.down0).turn).toBeCloseTo(0.35, 5);
  });

  it("putts have no selection beat or body turn", () => {
    const putt = buildTimeline({ ...stroke, club: { kind: "putter" } }, 3.0, false);
    expect(putt.full).toBe(false);
    expect(poseAt(putt, 0).phase).toBe("address");
    expect(poseAt(putt, putt.down0).turn).toBe(0);
  });
});

describe("helpers", () => {
  it("lerpAngle takes the short way round", () => {
    expect(lerpAngle(3.0, -3.0, 0.5)).toBeCloseTo(Math.PI, 1);
  });

  it("sampleTrajectory interpolates and clamps", () => {
    const pts = [
      [0, 0, 0, 0.02],
      [1, 1, 0, 0.02],
      [2, 1, 1, 0.02],
    ];
    expect(sampleTrajectory(pts, 0.5)).toEqual([0.5, 0, 0.02]);
    expect(sampleTrajectory(pts, 9)).toEqual([1, 1, 0.02]);
    expect(sampleTrajectory(pts, -1)).toEqual([0, 0, 0.02]);
  });

  it("maps world to three.js coordinates", () => {
    expect(toThree(1, 2, 3)).toEqual([1, 3, -2]);
  });
});
