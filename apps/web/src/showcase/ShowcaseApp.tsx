import { useEffect } from "react";
import { useStore } from "../store";
import { Scene } from "../scene/Scene";
import { Header } from "../ui/Header";
import { BrainPanel } from "../ui/BrainPanel";
import { ShotBar } from "../ui/ShotBar";
import { TechPanel } from "../ui/TechPanel";
import { Scorecard } from "../ui/Scorecard";
import { ModesPanel } from "../ui/ModesPanel";
import { BrainFiring, toggleFiring } from "../ui/BrainFiring";
import { CinemaHint } from "../ui/CinemaHint";
import { soundKey } from "../lib/sound";
import { cinemaKey, watchFullscreenExit } from "../ui/cinema";
import { ShowcaseControls } from "./ShowcaseControls";
import { ShowcaseSplash } from "./ShowcaseSplash";
import { closeSplash, initShowcase, nextShot, prevShot, primaryAction, replayShot } from "./controller";
import "./showcase.css";

/** The GitHub Pages build: the same scene and panels, driven by recorded runs instead of a backend. */
export function ShowcaseApp() {
  const cinema = useStore((s) => s.cinema);
  useEffect(() => {
    initShowcase();
    watchFullscreenExit();
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target;
      if (
        t instanceof HTMLInputElement ||
        t instanceof HTMLSelectElement ||
        e.metaKey ||
        e.ctrlKey ||
        e.altKey
      )
        return;
      const st = useStore.getState();
      if (!st.showcase?.started) {
        if (e.key === "Escape" && st.showcase?.run) closeSplash();
        return;
      }
      if (cinemaKey(e) || soundKey(e)) return;
      if (e.code === "Space") {
        e.preventDefault();
        primaryAction();
      } else if (e.key === "ArrowRight") nextShot();
      else if (e.key === "ArrowLeft") prevShot();
      else if (e.key === "r") replayShot();
      else if (e.key === "t") st.set({ techOpen: !st.techOpen, modesOpen: false });
      else if (e.key === "c") st.set({ cardOpen: !st.cardOpen });
      else if (e.key === "m") st.set({ modesOpen: !st.modesOpen, techOpen: false });
      else if (e.key === "b") toggleFiring();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <div className={`app showcase${cinema ? " cinema" : ""}`}>
      <Header />
      <main className="stage">
        <Scene />
        <Scorecard />
        <ShowcaseControls />
        <TechPanel />
        <ModesPanel />
        <ShowcaseSplash />
      </main>
      <BrainPanel />
      <ShotBar />
      <BrainFiring />
      <CinemaHint />
    </div>
  );
}
