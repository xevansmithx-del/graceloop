# Security policy

## Supported versions

GraceLoop is an alpha research tool. Only the newest GitHub release receives security
fixes.

## Reporting

Use GitHub private vulnerability reporting for security-sensitive issues. Do not open
a public issue containing credentials, restricted datasets, private research records,
or an unpatched exploit. Ordinary correctness and documentation issues may use the
public issue tracker.

## Security boundary

GraceLoop parses untrusted JSON, launches bounded optional adapter subprocesses, and
publishes local capsule directories. It rejects duplicate keys, non-finite numbers,
unknown schema fields, unsafe paths, symlinked or hard-linked inputs, source/capsule
inventory drift, parameter drift, output overflow, timeouts, and fixed-boundary
escalation.

Hashes establish byte identity, not truth, permission, independence, or currentness.
GraceLoop is not a sandbox, a signature system, a causal-inference engine, a medical
device, an experiment executor, or a source of clinical or laboratory authorization.
