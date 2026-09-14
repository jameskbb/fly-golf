import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { Club } from "@fly-golf/protocol";
import { clubFamily } from "./ClubIcon";

const course = JSON.parse(
  readFileSync(join(dirname(fileURLToPath(import.meta.url)), "../../public/showcase/course.json"), "utf8"),
);

describe("club icons", () => {
  it("has an icon for every club in the committed bag", () => {
    const bag = (course.clubs as unknown[]).map((c) => Club.parse(c));
    expect(bag.length).toBe(14);
    for (const club of bag) expect(clubFamily(club), club.id).toBeDefined();
  });

  it("maps each kind of club to its own family", () => {
    const byId = Object.fromEntries((course.clubs as Club[]).map((c) => [c.id, clubFamily(c)]));
    expect(byId).toMatchObject({
      driver: "driver",
      "3w": "wood",
      "5w": "wood",
      "4h": "hybrid",
      "7i": "iron",
      pw: "wedge",
      lw: "wedge",
      putter: "putter",
    });
  });

  it("shows no icon for a club it does not know", () => {
    expect(clubFamily({ kind: "spoon" as Club["kind"] })).toBeUndefined();
    expect(clubFamily(undefined)).toBeUndefined();
  });
});
