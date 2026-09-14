import type { Club } from "@fly-golf/protocol";

/** One line-icon per club family. Every club in the bag has a `kind` (services/sim clubs.py). */
export type ClubFamily = "driver" | "wood" | "hybrid" | "iron" | "wedge" | "putter";

const FAMILY_BY_KIND: Record<string, ClubFamily> = {
  driver: "driver",
  wood: "wood",
  hybrid: "hybrid",
  iron: "iron",
  wedge: "wedge",
  putter: "putter",
};

export function clubFamily(club: Pick<Club, "kind"> | null | undefined): ClubFamily | undefined {
  return club ? FAMILY_BY_KIND[club.kind] : undefined;
}

// 24x24, shaft coming in from the top right, head at the bottom left, stroked in currentColor.
const SHAPES: Record<ClubFamily, string> = {
  // Big round head.
  driver: "M19.5 2 13.5 13 M13.5 13C15 15.5 13 21 8 21C4 21 2 19 2.5 16.5C3 14 7 12.5 13.5 13Z",
  // Same profile, smaller head.
  wood: "M19.5 2 14 14 M14 14C15 16.5 13.3 20 9.8 20C7 20 5.3 18.6 5.7 16.7C6.1 14.9 9.5 13.7 14 14Z",
  // Compact head with a flat sole and a rounded back.
  hybrid: "M19.5 2 14.5 14 M14.5 14C15.4 15.8 15.3 19.5 11.2 19.5H7.6C6.3 19.5 6.1 17.9 7.3 17.2Z",
  // Thin blade.
  iron: "M19.5 2 15 14 M15 14 15.6 19.5H7.2C6.1 19.5 6 17.8 7.2 17.3Z",
  // Taller, lofted blade with grooves.
  wedge: "M19.5 2 15 13 M15 13 15.6 20H7.4C5.2 20 5 16.2 7 15.3Z M9 17.9H13.4 M9.4 16.3H13.6",
  // Flat blade.
  putter:
    "M18 2 14.5 15 M5 15H16.5A1 1 0 0 1 17.5 16V18.5A1 1 0 0 1 16.5 19.5H5A1 1 0 0 1 4 18.5V16A1 1 0 0 1 5 15Z",
};

/** Decorative: the club's name is always rendered next to it, so the icon is hidden from screen readers. */
export function ClubIcon({ club }: { club: Pick<Club, "kind"> | null | undefined }) {
  const family = clubFamily(club);
  if (!family) return null;
  return (
    <svg
      className={`club-icon club-icon-${family}`}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      <path d={SHAPES[family]} />
    </svg>
  );
}
