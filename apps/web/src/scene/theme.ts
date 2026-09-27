/**
 * How a course hole is lit and painted, by the hole's `theme` (from the backend's course
 * geometry). One table: the scene, the ground, the water and the trees all read their colours and
 * lights from here, so a theme is changed in one place.
 *
 * "parkland" is the front nine exactly as it has always looked (every value below is the constant
 * the renderer used before themes existed). "dusk" is the back nine: a low golden-hour sun, long
 * shadows, cooler and deeper greens, heather-tinged rough, copper-leaved trees, warm sand and dark
 * water that catches the sunset. Legibility wins over mood: the ball, the fly, the target line and
 * the surfaces must stay easy to read, so the dusk ground is lit with a strong sky fill.
 */
import type { HoleTheme } from "@fly-golf/protocol";

type RGB = [number, number, number];
type XYZ = [number, number, number];

interface TreeTint {
  hue: number; // HSL hue, plus up to `hueSpread` at random
  hueSpread: number;
  sat: number;
  light: number; // HSL lightness, plus up to `lightSpread` at random
  lightSpread: number;
}

export interface Theme {
  id: HoleTheme;
  background: string;
  fog: string; // course fog (the practice green keeps its own)
  /** drei's physical Sky, or a painted gradient dome (GradientSky in Scene.tsx). */
  sky:
    | {
        kind: "physical";
        sunPosition: XYZ;
        turbidity: number;
        rayleigh: number;
        mieCoefficient: number;
        mieDirectionalG: number;
      }
    | {
        kind: "gradient";
        sunDirection: XYZ; // where the glow sits
        zenith: string;
        mid: string;
        horizon: string;
        glow: string;
        glowSize: number; // radians-ish: how wide the sun's glow spreads
      };
  hemisphere: { sky: string; ground: string; intensity: number };
  sun: { color: string; intensity: number; offset: XYZ; shadowBias: number }; // offset: from the fly
  ground: {
    rough: [string, string]; // mown stripes (dark, light)
    /** Instead of stripes: one base colour with soft, low-contrast heather patches and grain. */
    roughMottle?: { base: string; patch: string; grain: number };
    collarRough: string; // the collar's outer colour, blending the fringe into the rough
    fairway: [string, string];
    green: [string, string];
    fringe: string;
    tee: string;
    sand: RGB;
    rim: string;
  };
  water: {
    color: string;
    roughness: number;
    metalness: number;
    normalScale: number;
    bank: string;
    bankOpacity: number;
    /** A sky gradient the water reflects (zenith, horizon, sun glow), or none. */
    reflect?: { zenith: string; horizon: string; glow: string; intensity: number };
  };
  trees: { conifer: TreeTint; round: TreeTint; trunk: string; coniferShare: number };
  trail: string; // the ball's flight trace: it must stand out against the sky
}

const parkland: Theme = {
  id: "parkland",
  background: "#a9c9e6",
  fog: "#c3d8ea",
  sky: {
    kind: "physical",
    sunPosition: [60, 40, 30],
    turbidity: 5,
    rayleigh: 1.1,
    mieCoefficient: 0.004,
    mieDirectionalG: 0.8,
  },
  hemisphere: { sky: "#dcecff", ground: "#35552c", intensity: 0.75 },
  sun: { color: "#ffffff", intensity: 2.6, offset: [6, 10, 4], shadowBias: -0.0004 },
  ground: {
    rough: ["#2f6428", "#336c2b"],
    collarRough: "#2f6428",
    fairway: ["#4a9a3f", "#56a94a"],
    green: ["#3e8b3a", "#4b9d44"],
    fringe: "#358a37",
    tee: "#4fa447",
    sand: [222, 205, 158],
    rim: "#8f7a4c",
  },
  water: {
    color: "#2b6f86",
    roughness: 0.12,
    metalness: 0.35,
    normalScale: 0.55,
    bank: "#cfe7df",
    bankOpacity: 0.8,
  },
  trees: {
    conifer: { hue: 0.36, hueSpread: 0.04, sat: 0.42, light: 0.17, lightSpread: 0.07 },
    round: { hue: 0.27, hueSpread: 0.06, sat: 0.45, light: 0.22, lightSpread: 0.08 },
    trunk: "#4a3423",
    coniferShare: 0.5,
  },
  trail: "#ffb938",
};

// The sun sets to the west: its glow sits on the horizon ahead and to the left of a hole played
// north, the light comes low from the left so shadows run long across the fairway while the fly
// and the ball stay lit, and a strong sky fill keeps every surface readable.
const dusk: Theme = {
  id: "dusk",
  background: "#e7b48e",
  fog: "#e9b996",
  sky: {
    kind: "gradient",
    sunDirection: [-0.72, 0.05, -0.69],
    zenith: "#3d4d8c",
    mid: "#b98aa6",
    horizon: "#f6b77e",
    glow: "#ffe2a8",
    glowSize: 0.35,
  },
  hemisphere: { sky: "#ddd5f2", ground: "#4d3f36", intensity: 1.35 },
  sun: { color: "#ffc68c", intensity: 3.3, offset: [-10, 4.8, -2], shadowBias: -0.0006 },
  ground: {
    rough: ["#46683e", "#46683e"], // not drawn: roughMottle replaces the stripes
    roughMottle: { base: "#46683e", patch: "#5b5463", grain: 8 },
    collarRough: "#46683e",
    fairway: ["#3f9152", "#4a9e5c"],
    green: ["#2f8649", "#3a9656"],
    fringe: "#2f8046",
    tee: "#48a257",
    sand: [238, 202, 150],
    rim: "#9c7447",
  },
  water: {
    color: "#1c4a66",
    roughness: 0.1,
    metalness: 0.4,
    normalScale: 0.5,
    bank: "#d3e4e4",
    bankOpacity: 0.8,
    reflect: { zenith: "#2c3a6e", horizon: "#5f79a8", glow: "#ffcf8a", intensity: 0.6 },
  },
  trees: {
    conifer: { hue: 0.41, hueSpread: 0.04, sat: 0.34, light: 0.13, lightSpread: 0.06 },
    round: { hue: 0.04, hueSpread: 0.06, sat: 0.48, light: 0.21, lightSpread: 0.08 },
    trunk: "#3a2a20",
    coniferShare: 0.62,
  },
  trail: "#6fe3ff", // cool against the warm sky; the parkland amber would vanish into it
};

export const THEMES: Record<HoleTheme, Theme> = { parkland, dusk };

/** The theme a hole is drawn in: parkland for the practice green, a hole without a theme (recorded
 *  before themes existed) or a theme this build does not know. */
export function themeFor(hole?: { theme?: string } | null): Theme {
  const id = hole?.theme;
  return id && Object.prototype.hasOwnProperty.call(THEMES, id) ? THEMES[id as HoleTheme] : parkland;
}
