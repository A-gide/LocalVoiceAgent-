// TypeScript contract generator (pinned).
//
// Reads the normalized JSON Schema on stdin and writes the generated
// TypeScript to stdout.  Any failure exits non-zero so the codegen chain can
// abort instead of writing a partial artifact.

import { compile } from 'json-schema-to-typescript';

async function readStdin() {
  const chunks = [];
  for await (const chunk of process.stdin) chunks.push(chunk);
  return Buffer.concat(chunks).toString('utf8');
}

const raw = await readStdin();
let schema;
try {
  schema = JSON.parse(raw);
} catch (err) {
  process.stderr.write(`invalid JSON on stdin: ${err.message}\n`);
  process.exit(4);
}

try {
  const ts = await compile(schema, 'LvaIpc', {
    bannerComment: '',
    additionalProperties: false,
    declareExternallyReferenced: true,
  });
  // Normalize to LF so the committed bytes are platform independent.
  process.stdout.write(ts.replace(/\r\n/g, '\n'));
} catch (err) {
  process.stderr.write(`json-schema-to-typescript failed: ${err.message}\n`);
  process.exit(6);
}