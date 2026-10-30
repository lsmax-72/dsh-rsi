/** The dsh build has no fallback model transport. A host runner is mandatory. */
export class CleanContextRunner {
  constructor(_options: unknown) {}
  async run(_params: unknown): Promise<never> {
    throw new Error('dsh-rsi requires an injected dsh model runner');
  }
}
