// The specs use four Node built-ins. @types/node is not a dependency of this project, so the few
// signatures they need are declared here (type-check only; Playwright runs the real modules).
declare module 'node:fs' {
  export function readFileSync(path: string): Uint8Array;
  export function readFileSync(path: string, encoding: 'utf-8'): string;
  export function writeFileSync(path: string, data: Uint8Array | string): void;
  export function mkdtempSync(prefix: string): string;
}
declare module 'node:path' {
  export function join(...parts: string[]): string;
}
declare module 'node:os' {
  export function tmpdir(): string;
}
declare const process: { platform: string; env: Record<string, string | undefined> };
