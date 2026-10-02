import { AsyncLocalStorage } from "node:async_hooks";
import type { LegacyMutationGuard } from "./legacy-mutation-guard.js";

export interface FormalMutationPermit {
  operationId: string;
  candidateHash: string;
  teamId: string;
  agentId: string;
  layers: ReadonlyArray<"skill" | "L1" | "L2" | "L3" | "wiki">;
}
interface Lease { active: boolean; children: Set<Promise<unknown>>; permit?: FormalMutationPermit }
const context = new AsyncLocalStorage<Lease>();
let tail: Promise<unknown> = Promise.resolve();

/** Single-process standalone boundary shared by legacy writes, activation and adoption.
 * Nested native writers are reentrant; detached child work cannot outlive its lease.
 * This is not a distributed lock and is never advertised for service/cloud deployments.
 */
export function withLocalMutationBoundary<T>(work: () => Promise<T> | T): Promise<T> {
  const parent = context.getStore();
  if (parent?.active) {
    const child = Promise.resolve().then(work);
    parent.children.add(child);
    void child.then(() => parent.children.delete(child), () => parent.children.delete(child));
    return child;
  }
  const run = tail.then(async () => {
    const lease: Lease = { active: true, children: new Set() };
    return context.run(lease, async () => {
      try { return await work(); }
      finally {
        while (lease.children.size) await Promise.allSettled([...lease.children]);
        lease.active = false;
      }
    });
  });
  tail = run.catch(() => {});
  return run;
}

/** Preserve the old path where governance is not wired by the standalone host. */
export function withLegacyMutation<T>(guard: LegacyMutationGuard | undefined, work: () => Promise<T>): Promise<T> {
  return guard ? withLocalMutationBoundary(work) : work();
}

/** The adoption coordinator supplies a persisted operation + frozen candidate hash.
 * It bypasses only matching native writer checks while the global boundary is held.
 */
export async function withFormalMutationPermit<T>(permit: FormalMutationPermit, work: () => Promise<T>): Promise<T> {
  if (!permit.operationId || !/^[a-f0-9]{64}$/.test(permit.candidateHash) || !permit.teamId || !permit.agentId || !permit.layers.length) throw new Error("FORMAL_MUTATION_PERMIT_INVALID");
  return withLocalMutationBoundary(async () => {
    const lease = context.getStore()!;
    if (lease.permit) throw new Error("FORMAL_MUTATION_PERMIT_NESTED");
    lease.permit = Object.freeze({ ...permit, layers: Object.freeze([...permit.layers]) });
    try { return await work(); }
    finally { delete lease.permit; }
  });
}

export function permitsFormalMutation(scope: { teamId?: string; agentId?: string; layer: string }): boolean {
  const permit = context.getStore()?.permit;
  return !!permit && scope.teamId === permit.teamId && scope.agentId === permit.agentId
    && permit.layers.includes(scope.layer as FormalMutationPermit["layers"][number]);
}
