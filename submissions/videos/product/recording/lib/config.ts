// Settings for a recording run, from the environment. Nothing here is written
// to disk: the session cookie in particular stays in this process.
//
//   AMBER_BASE_URL     the app to record (default: the hosted site)
//   AMBER_SESSION      value of the `amber_session` cookie for signed-in takes
//   RECORD_HEADED=1    show the browser window (if headless cannot draw the map)
//   RECORD_KEEP_FRAMES=1  keep the raw captured frames in out/recording/<scene>/

import path from "node:path";
import { fileURLToPath } from "node:url";

export const PROJECT_DIR = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../..",
);
export const RECORDINGS_DIR = path.join(PROJECT_DIR, "public", "recordings");
// Git-ignored scratch space for raw frames.
export const WORK_DIR = path.join(PROJECT_DIR, "out", "recording");

export const BASE_URL = (
  process.env.AMBER_BASE_URL ||
  "https://frontend-production-aa5a.up.railway.app"
).replace(/\/+$/, "");

// Name from apps/backend/src/backend/api/security.py (COOKIE_NAME).
export const SESSION_COOKIE_NAME = "amber_session";
export const SESSION_COOKIE = process.env.AMBER_SESSION || "";

export const HEADED = process.env.RECORD_HEADED === "1";
export const KEEP_FRAMES = process.env.RECORD_KEEP_FRAMES === "1";

export const FPS = 30;

// The page is laid out at 1440×810 CSS pixels and drawn at 4/3 device pixels
// per CSS pixel, so every frame is 1920×1080 with text a third larger than
// a 1920-wide layout would give: the video shows the recording at 1560 px.
export const VIEWPORT = { width: 1440, height: 810 };
export const DEVICE_SCALE = 4 / 3;
export const OUTPUT = { width: 1920, height: 1080 };

export const FFMPEG = process.env.FFMPEG || "/opt/homebrew/bin/ffmpeg";
