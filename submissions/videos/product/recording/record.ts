// Records screen takes into public/recordings/.
// Usage: npm run record                 (every take that can run now)
//        npm run record -- graph close  (only these scene ids)
// Signed-in takes run only with AMBER_SESSION set; see lib/config.ts.

import { SESSION_COOKIE } from "./lib/config.ts";
import { recordTake, type SceneTake } from "./lib/scene.ts";
import { arrive } from "./scenes/01-arrive.ts";
import { graph } from "./scenes/02-graph.ts";
import { relative } from "./scenes/03-relative.ts";
import { gap } from "./scenes/04-gap.ts";
import { close } from "./scenes/06-close.ts";

const TAKES: readonly SceneTake[] = [arrive, graph, relative, gap, close];

const requested = process.argv.slice(2);
const unknown = requested.filter((id) => !TAKES.some((t) => t.id === id));
if (unknown.length > 0) {
  console.error(
    `No take for ${unknown.join(", ")}. Takes: ${TAKES.map((t) => t.id).join(", ")}.`,
  );
  process.exit(1);
}

const chosen = TAKES.filter(
  (t) => requested.length === 0 || requested.includes(t.id),
);
for (const take of chosen) {
  if (take.signedIn && !SESSION_COOKIE) {
    if (requested.length === 0) {
      console.log(`${take.id}: skipped (needs AMBER_SESSION).`);
      continue;
    }
  }
  if (take.note) console.log(`${take.id}: ${take.note}`);
  await recordTake(take);
}
