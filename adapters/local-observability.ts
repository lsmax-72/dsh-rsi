// Only the original core's default no-op backend is available in the local build.
// Model usage, requests and outcomes are separately persisted by the dsh bridge.
import { NoopObservabilityBackend } from '../vendor/core/src/core/report/noop-backend.js';
const backend = new NoopObservabilityBackend();
export function getObservabilityBackend() { return backend; }
