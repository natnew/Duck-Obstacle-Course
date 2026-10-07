/** Top-down course renderer. World x runs left→right; world +y (robot's left) is up. */

import type { Frame, Trial } from "./types";

const VIEW = { xMin: -0.6, xMax: 3.4, yMin: -1.1, yMax: 1.1 };
const ASPECT = (VIEW.xMax - VIEW.xMin) / (VIEW.yMax - VIEW.yMin);

const COLOURS = {
  floor: "#f4f1ea",
  grid: "#e6e1d6",
  wall: "#6b7a8f",
  obstacle: "#d9742b",
  finish: "#2f9e44",
  start: "#868e96",
  trail: "#1c7ed6",
  robot: "#1864ab",
  robotFill: "#a5d8ff",
  heading: "#0b3d6b",
  left: "#1c7ed6",
  forward: "#e67700",
  right: "#7048e8",
  blocked: "rgba(224, 49, 49, 0.35)",
  clear: "rgba(47, 158, 68, 0.35)",
  contact: "#e03131",
  text: "#495057",
};

export const SECTOR_COLOURS = { left: COLOURS.left, forward: COLOURS.forward, right: COLOURS.right };

export function sectorOfColumn(column: number): "left" | "forward" | "right" {
  return column < 3 ? "left" : column < 5 ? "forward" : "right";
}

export class CourseRenderer {
  private readonly ctx: CanvasRenderingContext2D;
  private scale = 1;

  constructor(private readonly canvas: HTMLCanvasElement) {
    const ctx = canvas.getContext("2d");
    if (!ctx) {
      throw new Error("2D canvas is not available");
    }
    this.ctx = ctx;
  }

  /** Match the backing store to the CSS size and device pixel ratio. */
  resize(): void {
    const dpr = window.devicePixelRatio || 1;
    const cssWidth = this.canvas.clientWidth || 960;
    const cssHeight = cssWidth / ASPECT;
    this.canvas.style.height = `${cssHeight}px`;
    this.canvas.width = Math.round(cssWidth * dpr);
    this.canvas.height = Math.round(cssHeight * dpr);
    this.scale = this.canvas.width / (VIEW.xMax - VIEW.xMin);
  }

  private px(x: number): number {
    return (x - VIEW.xMin) * this.scale;
  }

  private py(y: number): number {
    return (VIEW.yMax - y) * this.scale;
  }

  private m(metres: number): number {
    return metres * this.scale;
  }

  draw(trial: Trial | null, frameIndex: number): void {
    const { ctx } = this;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.fillStyle = COLOURS.floor;
    ctx.fillRect(0, 0, this.canvas.width, this.canvas.height);
    this.drawGrid();
    if (!trial) {
      return;
    }
    this.drawCourse(trial);
    const frames = trial.result.frames;
    const frame = frames[Math.min(frameIndex, frames.length - 1)];
    if (!frame) {
      return;
    }
    this.drawTrail(frames, frameIndex);
    this.drawRays(trial, frame);
    this.drawThresholds(trial, frame);
    this.drawRobot(trial, frame, frames[frameIndex - 1]);
  }

  private drawGrid(): void {
    const { ctx } = this;
    ctx.strokeStyle = COLOURS.grid;
    ctx.lineWidth = 1;
    for (let x = Math.ceil(VIEW.xMin * 2) / 2; x <= VIEW.xMax; x += 0.5) {
      ctx.beginPath();
      ctx.moveTo(this.px(x), 0);
      ctx.lineTo(this.px(x), this.canvas.height);
      ctx.stroke();
    }
    for (let y = Math.ceil(VIEW.yMin * 2) / 2; y <= VIEW.yMax; y += 0.5) {
      ctx.beginPath();
      ctx.moveTo(0, this.py(y));
      ctx.lineTo(this.canvas.width, this.py(y));
      ctx.stroke();
    }
    ctx.fillStyle = COLOURS.text;
    ctx.font = `${Math.max(10, this.m(0.06))}px system-ui, sans-serif`;
    ctx.textBaseline = "top";
    for (let x = 0; x <= 3; x += 1) {
      ctx.fillText(`${x} m`, this.px(x) + 3, this.py(VIEW.yMax) + 3);
    }
  }

  private drawCourse(trial: Trial): void {
    const { ctx } = this;
    const { course } = trial;
    for (const [name, xmin, xmax, ymin, ymax] of trial.boxes) {
      ctx.fillStyle = name.startsWith("wall") ? COLOURS.wall : COLOURS.obstacle;
      ctx.fillRect(this.px(xmin), this.py(ymax), this.m(xmax - xmin), this.m(ymax - ymin));
    }
    // Finish marker: a non-colliding site in the MJCF, so drawn as a dashed line.
    ctx.strokeStyle = COLOURS.finish;
    ctx.lineWidth = Math.max(2, this.m(0.02));
    ctx.setLineDash([this.m(0.06), this.m(0.04)]);
    ctx.beginPath();
    ctx.moveTo(this.px(course.goal_x), this.py(course.half_width - 0.1));
    ctx.lineTo(this.px(course.goal_x), this.py(-(course.half_width - 0.1)));
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = COLOURS.finish;
    ctx.font = `600 ${Math.max(11, this.m(0.07))}px system-ui, sans-serif`;
    ctx.textBaseline = "bottom";
    ctx.fillText("finish", this.px(course.goal_x) + 6, this.py(-(course.half_width - 0.1)) - 2);
    ctx.fillStyle = COLOURS.start;
    ctx.beginPath();
    ctx.arc(this.px(course.start[0]), this.py(course.start[1]), this.m(0.03), 0, Math.PI * 2);
    ctx.fill();
    ctx.fillText("start", this.px(course.start[0]) - this.m(0.08), this.py(-0.12));
  }

  private drawTrail(frames: Frame[], upTo: number): void {
    if (upTo < 1) {
      return;
    }
    const { ctx } = this;
    ctx.strokeStyle = COLOURS.trail;
    ctx.lineWidth = Math.max(1.5, this.m(0.012));
    ctx.beginPath();
    for (let i = 0; i <= upTo && i < frames.length; i += 1) {
      const f = frames[i];
      if (!f) {
        continue;
      }
      if (i === 0) {
        ctx.moveTo(this.px(f.x), this.py(f.y));
      } else {
        ctx.lineTo(this.px(f.x), this.py(f.y));
      }
    }
    ctx.stroke();
  }

  private sensorOrigin(trial: Trial, frame: Frame): [number, number] {
    const offset = trial.assumptions.sensor_offset_m;
    return [frame.x + offset * Math.cos(frame.heading), frame.y + offset * Math.sin(frame.heading)];
  }

  private drawRays(trial: Trial, frame: Frame): void {
    const { ctx } = this;
    const [ox, oy] = this.sensorOrigin(trial, frame);
    const fov = (trial.assumptions.horizontal_fov_deg * Math.PI) / 180;
    const maxRange = trial.assumptions.max_range_m;
    ctx.lineWidth = Math.max(1, this.m(0.008));
    frame.rays.forEach((hit, column) => {
      const angle = frame.heading + fov / 2 - ((column + 0.5) * fov) / 8;
      const length = hit ?? maxRange;
      const ex = ox + length * Math.cos(angle);
      const ey = oy + length * Math.sin(angle);
      const colour = SECTOR_COLOURS[sectorOfColumn(column)];
      ctx.strokeStyle = colour;
      ctx.globalAlpha = hit === null ? 0.25 : 0.7;
      ctx.beginPath();
      ctx.moveTo(this.px(ox), this.py(oy));
      ctx.lineTo(this.px(ex), this.py(ey));
      ctx.stroke();
      ctx.globalAlpha = 1;
      if (hit !== null) {
        ctx.fillStyle = colour;
        ctx.beginPath();
        ctx.arc(this.px(ex), this.py(ey), this.m(0.018), 0, Math.PI * 2);
        ctx.fill();
      }
    });
  }

  /** Hysteresis bands: blocked below `blocked_m`, released above `clear_m`. */
  private drawThresholds(trial: Trial, frame: Frame): void {
    const { ctx } = this;
    const [ox, oy] = this.sensorOrigin(trial, frame);
    const fov = (trial.assumptions.horizontal_fov_deg * Math.PI) / 180;
    const start = -(frame.heading + fov / 2);
    const end = -(frame.heading - fov / 2);
    for (const [radius, colour] of [
      [trial.config.policy.clear_m, COLOURS.clear],
      [trial.config.policy.blocked_m, COLOURS.blocked],
    ] as const) {
      ctx.strokeStyle = colour;
      ctx.lineWidth = Math.max(1, this.m(0.01));
      ctx.beginPath();
      ctx.arc(this.px(ox), this.py(oy), this.m(radius), start, end);
      ctx.stroke();
    }
  }

  private drawRobot(trial: Trial, frame: Frame, previous: Frame | undefined): void {
    const { ctx } = this;
    const radius = trial.assumptions.robot_radius_m;
    const contact = previous !== undefined && frame.collisions > previous.collisions;
    const latched = frame.latched !== null;
    ctx.fillStyle = COLOURS.robotFill;
    ctx.strokeStyle = contact ? COLOURS.contact : COLOURS.robot;
    ctx.lineWidth = Math.max(2, this.m(0.015));
    ctx.beginPath();
    ctx.arc(this.px(frame.x), this.py(frame.y), this.m(radius), 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
    if (latched) {
      ctx.strokeStyle = frame.latched === "left" ? COLOURS.left : COLOURS.right;
      ctx.setLineDash([this.m(0.02), this.m(0.02)]);
      ctx.beginPath();
      ctx.arc(this.px(frame.x), this.py(frame.y), this.m(radius + 0.03), 0, Math.PI * 2);
      ctx.stroke();
      ctx.setLineDash([]);
    }
    ctx.strokeStyle = COLOURS.heading;
    ctx.lineWidth = Math.max(2, this.m(0.015));
    ctx.beginPath();
    ctx.moveTo(this.px(frame.x), this.py(frame.y));
    ctx.lineTo(
      this.px(frame.x + radius * 1.3 * Math.cos(frame.heading)),
      this.py(frame.y + radius * 1.3 * Math.sin(frame.heading)),
    );
    ctx.stroke();
  }
}
