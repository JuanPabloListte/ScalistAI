// Firma un JWT para armar sesiones del entorno DEMO sin tipear contraseñas.
// Solo para secretos/llaves que vos definiste en el script de entorno demo local.
//
// Como módulo:
//   import { firmarJwt } from './token-jwt.mjs';
//   const t = firmarJwt({ secreto: 'demo-secret…', payload: { sub: id, email }, ttl: 8 * 3600 });
//   // RS256: firmarJwt({ llavePrivada: readFileSync('demo-key.pem'), alg: 'RS256', payload })
//
// CLI:
//   node token-jwt.mjs --secreto <s> --payload '{"sub":"…","email":"…"}' [--ttl 28800] [--alg HS256]
//   node token-jwt.mjs --llave demo-key.pem --alg RS256 --payload '{…}'

import { createHmac, createSign } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const b64u = (v) => Buffer.from(typeof v === 'string' ? v : JSON.stringify(v)).toString('base64url');

export function firmarJwt({ secreto, llavePrivada, payload, ttl = 8 * 3600, alg = 'HS256', encabezado = {} }) {
  const ahora = Math.floor(Date.now() / 1000);
  const head = b64u({ alg, typ: 'JWT', ...encabezado });
  const body = b64u({ iat: ahora, exp: ahora + ttl, ...payload });
  const datos = `${head}.${body}`;
  let firma;
  if (alg === 'HS256' || alg === 'HS384' || alg === 'HS512') {
    if (!secreto) throw new Error(`${alg} requiere "secreto"`);
    firma = createHmac(`sha${alg.slice(2)}`, secreto).update(datos).digest('base64url');
  } else if (alg === 'RS256') {
    if (!llavePrivada) throw new Error('RS256 requiere "llavePrivada" (PEM)');
    firma = createSign('RSA-SHA256').update(datos).sign(llavePrivada).toString('base64url');
  } else {
    throw new Error(`Algoritmo no soportado: ${alg}`);
  }
  return `${datos}.${firma}`;
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  const a = process.argv.slice(2);
  const v = (k) => {
    const i = a.indexOf(k);
    return i >= 0 ? a[i + 1] : undefined;
  };
  const alg = v('--alg') ?? 'HS256';
  const token = firmarJwt({
    alg,
    secreto: v('--secreto'),
    llavePrivada: v('--llave') ? readFileSync(v('--llave')) : undefined,
    payload: JSON.parse(v('--payload') ?? '{}'),
    ttl: Number(v('--ttl') ?? 8 * 3600),
  });
  console.log(token);
}
