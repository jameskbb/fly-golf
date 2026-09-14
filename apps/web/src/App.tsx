import { useEffect } from "react";
import { advance, newHole, refreshStatus, replay, startLiveConnection } from "./actions";
import { useStore } from "./store";
import { Scene } from "./scene/Scene";
import { Header } from "./ui/Header";
import { BrainPanel } from "./ui/BrainPanel";
import { ShotBar } from "./ui/ShotBar";
import { Controls } from "./ui/Controls";
import { TechPanel } from "./ui/TechPanel";
import { RunsPanel } from "./ui/RunsPanel";
import { Scorecard } from "./ui/Scorecard";
import { ModesPanel } from "./ui/ModesPanel";

export function App() {
  const connection = useStore((s) => s.connection);
  const connectionMessage = useStore((s) => s.connectionMessage);

  useEffect(() => {
    void refreshStatus();
    return startLiveConnection();
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.metaKey || e.ctrlKey) return;
      const st = useStore.getState();
      if (e.code === "Space") {
        e.preventDefault();
        if (!st.busy && !st.playback) advance();
      } else if (e.key === "n") void newHole();
      else if (e.key === "r") replay();
      else if (e.key === "t") st.set({ techOpen: !st.techOpen });
      else if (e.key === "c") st.set({ cardOpen: !st.cardOpen });
      else if (e.key === "m") st.set({ modesOpen: !st.modesOpen, techOpen: false, runsOpen: false });
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <div className="app">
      <Header />
      <main className="stage">
        <Scene />
        <Scorecard />
        <Controls />
        <TechPanel />
        <RunsPanel />
        <ModesPanel />
        {connection === "mismatch" && (
          <div className="overlay">
            <div className="overlay-card">
              <h2>Protocol version mismatch</h2>
              <p>{connectionMessage}</p>
              <p className="muted">Rebuild the frontend and backend from the same commit, then reload.</p>
            </div>
          </div>
        )}
      </main>
      <BrainPanel />
      <ShotBar />
    </div>
  );
}
