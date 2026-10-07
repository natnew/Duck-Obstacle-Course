/** Shapes returned by `duck_course.proxy.run_trial` and `sweep` (JSON over Pyodide). */

export type Strategy = "clearance" | "right-hand";

export type ActionName = "forward" | "left" | "right" | "stop" | "recover" | "done";

export type EpisodeStatus =
  | "running"
  | "success"
  | "timeout"
  | "stalled"
  | "fallen"
  | "out_of_bounds"
  | "policy_stop";

export interface Obstacle {
  x: number;
  y: number;
  half_size: [number, number, number];
}

export interface Course {
  seed: number | null;
  start: [number, number];
  goal_x: number;
  half_width: number;
  obstacles: Obstacle[];
}

/** `(name, xmin, xmax, ymin, ymax)` — obstacles and side walls. */
export type Box = [string, number, number, number, number];

export interface Sectors {
  left: number;
  forward: number;
  right: number;
  usable: boolean;
}

export interface Frame {
  t: number;
  x: number;
  y: number;
  heading: number;
  sectors: Sectors;
  /** Nearest hit per ToF column in metres, column 0 leftmost; null is a miss. */
  rays: (number | null)[];
  action: ActionName | null;
  latched: "left" | "right" | null;
  collisions: number;
  status: EpisodeStatus;
}

export interface PolicyConfig {
  blocked_m: number;
  clear_m: number;
  forward_m_s: number;
  turn_rad_s: number;
}

export interface EvaluationConfig {
  timeout_s: number;
  stall_s: number;
  progress_m: number;
  recovery_s: number;
  startup_s: number;
  minimum_height_m: number;
  minimum_up_cos: number;
}

export interface ProxyAssumptions {
  dt_s: number;
  robot_radius_m: number;
  sensor_offset_m: number;
  horizontal_fov_deg: number;
  max_range_m: number;
  trunk_height_m: number;
}

export interface TrialResult {
  status: EpisodeStatus;
  elapsed_s: number;
  distance_m: number;
  collision_events: number;
  falls: number;
  upright: boolean;
  scored: boolean;
  strategy: Strategy;
  seed: number | null;
  course_id: string;
  termination: "episode" | "policy_stop";
  final_pose: [number, number, number];
  action_counts: Partial<Record<ActionName, number>>;
  action_trace_sha256: string;
  steps: number;
  frames?: Frame[];
}

export interface Geometry {
  lateral_gaps: { obstacle: number; left_gap_m: number; right_gap_m: number }[];
  longitudinal_spacing_m: number[];
  min_widest_gap_m: number | null;
}

export interface Trial {
  course: Course;
  boxes: Box[];
  geometry: Geometry;
  assumptions: ProxyAssumptions;
  config: { policy: PolicyConfig; evaluation: EvaluationConfig };
  result: TrialResult & { frames: Frame[] };
}

export interface StrategySummary {
  episodes: number;
  scored_episodes: number;
  layouts: number;
  statuses: Record<string, number>;
  success_rate: number;
  collision_free_rate: number | null;
  upright_rate: number | null;
  mean_elapsed_s: number | null;
  mean_collision_events: number | null;
}

export type Summary = Record<Strategy, StrategySummary>;
