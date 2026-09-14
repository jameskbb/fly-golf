import type { ControllerInfo } from "@fly-golf/protocol";
import type { ControllerId } from "../lib/api";
import type { PersonaId } from "../scene/looks";

/** Who the brain plays as: its 3D model on the course and its headshot on the picker. */
export interface Persona {
  id: PersonaId;
  name: string;
  look: string; // what the model looks like and why, in plain words
}

/** The three brains the fly can play with, and how the UI names and colours them everywhere. */
export interface BrainMode {
  id: ControllerId;
  tone: "mock" | "live" | "trained";
  name: string; // short name (buttons, scorecard)
  kicker: string; // one-line category, shown above the name
  sub: string; // what it is, in plain words
  neural: boolean; // does a simulated nervous system produce the stroke?
  persona: Persona;
}

export const BRAINS: BrainMode[] = [
  {
    id: "mock",
    tone: "mock",
    name: "Mock",
    kicker: "NO BRAIN · TEST STAND-IN",
    sub: "Hand-written golf rules. No neurons are simulated.",
    neural: false,
    persona: {
      id: "windup",
      name: "the wind-up",
      look: "A clockwork tin fly with a key in its back. There is nothing inside to think with: it swings the way its hand-written rules wind it up to.",
    },
  },
  {
    id: "malecns",
    tone: "live",
    name: "MaleCNS",
    kicker: "REAL CONNECTOME · UNTRAINED",
    sub: "166k simulated neurons, read out with fixed a-priori rules.",
    neural: true,
    persona: {
      id: "fly",
      name: "the wild fly",
      look: "A plain fruit fly, straight off the connectome. It has never had a lesson.",
    },
  },
  {
    id: "malecns-trained",
    tone: "trained",
    name: "Trained",
    kicker: "REAL CONNECTOME · PRACTISED",
    sub: "The same neurons, read out with weights learned from practice shots.",
    neural: true,
    persona: {
      id: "golfer",
      name: "the club member",
      look: "The same fly with the same neurons, dressed for the club in a tam, argyle and a glove. Only its readout has practised.",
    },
  },
];

export const brainById = (id: string | undefined): BrainMode | undefined => BRAINS.find((b) => b.id === id);

/** The 3D model for a controller. An unknown mock never borrows a real fly's body. */
export function personaFor(controller: Pick<ControllerInfo, "id" | "is_mock">): PersonaId {
  return brainById(controller.id)?.persona.id ?? (controller.is_mock ? "windup" : "fly");
}
