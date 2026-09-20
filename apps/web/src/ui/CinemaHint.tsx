import { useStore } from "../store";

/** The way out of cinema mode, shown briefly after entering it by hand (never for ?cinema=1). */
export function CinemaHint() {
  const cinema = useStore((s) => s.cinema);
  const at = useStore((s) => s.cinemaHintAt);
  if (!cinema || !at) return null;
  return (
    <div className="cinema-hint" key={at} role="status">
      Fullscreen · press <kbd>F</kbd> or <kbd>Esc</kbd> to bring the panels back
    </div>
  );
}
