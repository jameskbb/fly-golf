import { describe, expect, it } from "vitest";
import { cinemaFromSearch } from "./cinema";

describe("cinema mode from the URL", () => {
  it("turns on for ?cinema=1 and its spellings", () => {
    for (const q of ["?cinema=1", "?cinema", "?cinema=true", "?cinema=YES", "?run=x&cinema=on&shot=3"]) {
      expect(cinemaFromSearch(q)).toBe(true);
    }
  });
  it("stays off otherwise", () => {
    for (const q of ["", "?cinema=0", "?cinema=false", "?run=trained-eighteen-s07&shot=14", "?cinemas=1"]) {
      expect(cinemaFromSearch(q)).toBe(false);
    }
  });
});
