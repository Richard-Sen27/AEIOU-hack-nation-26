import {getStaticFiles, watchPublicFolder} from '@remotion/studio';
import {useEffect, useState} from 'react';
import {getRemotionEnvironment, staticFile} from 'remotion';

type PublicFile = {
  readonly name: string;
  readonly sizeInBytes: number;
  readonly lastModified: number;
};

const findFile = (files: readonly PublicFile[], name: string) =>
  files.find((f) => f.name === name);

// How often the Studio re-checks a file that just appeared or changed, and
// how many equal sizes in a row count as "finished copying".
const POLL_MS = 1000;
const STABLE_CHECKS = 2;

const sizeOnServer = async (src: string): Promise<number | null> => {
  try {
    const response = await fetch(src, {method: 'HEAD', cache: 'no-store'});
    const length = response.headers.get('content-length');
    return response.ok && length !== null ? Number(length) : null;
  } catch {
    return null;
  }
};

// The src for `name` (a path inside public/), or null while it is missing.
//
// getStaticFiles() lists public/ in the Studio and during rendering (the
// bundler snapshots the folder when the render starts). Outside Studio and
// rendering (Player, Node) the list is empty and every file counts as missing.
//
// In the Studio the hook also follows the folder, so a dropped-in file
// replaces its placeholder without a reload. A file that appears while the
// Studio is open is only used once its size has stopped growing: opening a
// half-copied video crashes the preview, and the folder watcher does not
// report every write. The src carries the size, so media reloads whenever
// the file is replaced.
export const usePublicFile = (name: string): string | null => {
  const [size, setSize] = useState<number | null>(
    () => findFile(getStaticFiles(), name)?.sizeInBytes ?? null,
  );

  useEffect(() => {
    if (!getRemotionEnvironment().isStudio) {
      return;
    }

    let generation = 0;
    const settle = async () => {
      const current = ++generation;
      const src = staticFile(name);
      let last: number | null = null;
      let equalChecks = 0;
      while (current === generation && equalChecks < STABLE_CHECKS) {
        await new Promise((resolve) => setTimeout(resolve, POLL_MS));
        const next = await sizeOnServer(src);
        if (next === null) {
          return;
        }
        equalChecks = next === last ? equalChecks + 1 : 0;
        last = next;
      }
      if (current === generation) {
        setSize(last);
      }
    };

    const onFolderChange = (files: readonly PublicFile[]) => {
      if (!findFile(files, name)) {
        generation++;
        setSize(null);
        return;
      }
      settle();
    };

    let cancelWatch = () => {};
    try {
      cancelWatch = watchPublicFolder(onFolderChange).cancel;
    } catch {
      // Read-only Studio cannot watch the folder; the initial list stands.
    }
    return () => {
      generation++;
      cancelWatch();
    };
  }, [name]);

  return size === null ? null : `${staticFile(name)}?v=${size}`;
};
