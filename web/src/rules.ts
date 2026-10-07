/** Explains which rule in `ReactivePolicy.decide` / `Episode.update` produced a frame's action. */

import type { Frame, PolicyConfig } from "./types";

export type RuleId =
  | "episode"
  | "invalid"
  | "latched"
  | "clear"
  | "blocked_ahead"
  | "blocked_left"
  | "blocked_right";

export interface RuleRow {
  id: RuleId;
  condition: string;
  action: string;
}

export const RULES: RuleRow[] = [
  { id: "clear", condition: "all sectors ≥ blocked_m", action: "FORWARD" },
  { id: "blocked_ahead", condition: "forward < blocked_m", action: "TURN toward clearance (right-hand: RIGHT)" },
  { id: "blocked_left", condition: "left < blocked_m", action: "TURN RIGHT" },
  { id: "blocked_right", condition: "right < blocked_m", action: "TURN LEFT" },
  { id: "latched", condition: "turn latched until all sectors ≥ clear_m", action: "keep turning" },
  { id: "invalid", condition: "depth frame unusable", action: "STOP (fail closed)" },
  { id: "episode", condition: "evaluation override", action: "RECOVER / STOP / DONE" },
];

export function activeRule(frame: Frame, previous: Frame | undefined, policy: PolicyConfig): RuleId {
  if (frame.action === null || frame.action === "done" || frame.action === "recover" || frame.status !== "running") {
    return "episode";
  }
  if (!frame.sectors.usable || frame.action === "stop") {
    return "invalid";
  }
  const { left, forward, right } = frame.sectors;
  const nearest = Math.min(left, forward, right);
  if (previous?.latched && nearest < policy.clear_m && frame.action === previous.latched) {
    return "latched";
  }
  if (nearest >= policy.blocked_m) {
    return "clear";
  }
  if (forward < policy.blocked_m) {
    return "blocked_ahead";
  }
  return left < policy.blocked_m ? "blocked_left" : "blocked_right";
}

export function describeStatus(status: Frame["status"]): string {
  switch (status) {
    case "running":
      return "Running";
    case "success":
      return "Success — upright trunk crossed the finish line";
    case "stalled":
      return "Stalled — no 5 cm progress for 10 s";
    case "timeout":
      return "Timeout — episode limit reached";
    case "fallen":
      return "Fallen — not reachable in the proxy";
    case "out_of_bounds":
      return "Out of bounds";
    case "policy_stop":
      return "Policy stopped on invalid depth";
  }
}
