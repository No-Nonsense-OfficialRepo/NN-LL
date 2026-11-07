// Download official Microsoft development packages into this directory only.
// No installer, package-manager global cache or downloaded executable is run.
import { readFile, mkdir, stat, rename, rm } from 'node:fs/promises';
import { createReadStream, createWriteStream } from 'node:fs';
import { createHash } from 'node:crypto';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { pipeline } from 'node:stream/promises';
import { Readable } from 'node:stream';
const root = dirname(fileURLToPath(import.meta.url));
const lock = JSON.parse(await readFile(join(root, 'wdk-lock.json'), 'utf8'));
const destination = join(root, 'out', 'wdk-downloads');
await mkdir(destination, { recursive: true });
async function digest(path) {
  const hash = createHash('sha256');
  for await (const part of createReadStream(path)) hash.update(part);
  return hash.digest('hex');
}
for (const pkg of lock.packages) {
  const name = `${pkg.id}.${lock.package_version}.nupkg`;
  const target = join(destination, name);
  let present = false;
  try { present = (await stat(target)).isFile(); } catch (error) { if (error.code !== 'ENOENT') throw error; }
  if (present) {
    if ((await stat(target)).size !== pkg.bytes || await digest(target) !== pkg.sha256)
      throw new Error(`Existing package failed the pinned hash check: ${name}`);
    console.log(`Verified cached ${name}`);
    continue;
  }
  const url = new URL(`${pkg.id}/${lock.package_version}/${name}`, lock.source);
  if (url.origin !== 'https://api.nuget.org') throw new Error('Unexpected package origin');
  const partial = target + '.download';
  try {
    const response = await fetch(url);
    if (!response.ok || !response.body) throw new Error(`Download failed: ${name} (${response.status})`);
    await pipeline(Readable.fromWeb(response.body), createWriteStream(partial, { flags: 'wx' }));
    if ((await stat(partial)).size !== pkg.bytes || await digest(partial) !== pkg.sha256)
      throw new Error(`Downloaded package failed the pinned hash check: ${name}`);
    await rename(partial, target);
    console.log(`Downloaded and verified ${name} (${pkg.bytes} bytes)`);
  } catch (error) {
    await rm(partial, { force: true });
    throw error;
  }
}
