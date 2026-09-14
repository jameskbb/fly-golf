import type { PersonaId } from "../scene/looks";
import { usePortrait } from "../scene/portraits";
import type { BrainMode } from "./brains";

/** A brain's persona, rendered from its 3D model, on a tile in the brain's colour. */
export function Headshot({
  persona,
  tone,
  size,
}: {
  persona: PersonaId;
  tone: BrainMode["tone"];
  size?: "lg";
}) {
  const src = usePortrait(persona);
  return (
    <span className={`headshot ${tone}${size ? ` ${size}` : ""}`} aria-hidden="true">
      {src && <img src={src} alt="" draggable={false} />}
    </span>
  );
}
