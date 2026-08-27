const response = await fetch("http://127.0.0.1:8080/health/ready", {
  signal: AbortSignal.timeout(3_000),
});
const readiness = await response.json();
if (
  !response.ok ||
  readiness.status !== "ready" ||
  readiness.protocol_version !== 1 ||
  !/^sha256:[a-f0-9]{64}$/.test(readiness.runtime_image_id) ||
  typeof readiness.metrics !== "object" ||
  readiness.metrics === null ||
  !Number.isInteger(readiness.metrics.readiness_checks) ||
  !Number.isInteger(readiness.metrics.remaining_labeled_resources)
) {
  process.exit(1);
}
