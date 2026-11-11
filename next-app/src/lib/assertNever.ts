export function assertNever(x: never): never {
  throw new Error(`Unhandled value: ${String(x)}`);
}
