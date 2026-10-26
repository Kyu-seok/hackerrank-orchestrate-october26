# Deletion Audit

Auditing whether a person's deletion request was truly carried out across every system as of the audit time, and planning what remains to be done.

## Language

### People and identity

**Subject**:
The person whose deletion request is being audited, identified by a stable `user_id`.
_Avoid_: User, customer, requester

**Identifier set**:
Every current and historical direct identifier of a Subject: name, email, phone, and email hash.
_Avoid_: Aliases, PII list

### Records and evidence

**Resource**:
One record held by one system, keyed by its `system_id` and `resource_id`.
_Avoid_: Record, row, document

**Replica**:
A read, failover, regional, or reporting copy of a system's data; a row found there is a Resource of the system it copies.
_Avoid_: Secondary database, mirror

**Evidence item**:
Anything citable as proof of a Resource's state: a `file_id`, `activity_id`, or `audit_id`.
_Avoid_: Proof, source

**Claim**:
A state asserted by a workflow (`reported_status` on a request, `reported_result` on an activity) that is never proof on its own.
_Avoid_: Status, result

**Observation**:
A Resource's state as actually seen in a snapshot, readback, or Check activity at a known capture time.
_Avoid_: Fact, reading

**Check activity**:
An activity that inspects and reports a Resource's current state (`CHECK_DATA_FLOW`, `CHECK_RESTORE_ACCESS`); it yields an Observation.
_Avoid_: Probe, status check

**Action activity**:
An activity that attempts to change a Resource (delete, redact, anonymize, disable, block); its result is only a Claim.
_Avoid_: Operation, task

**Audit cutoff**:
The case's `audit_at`; nothing captured after it counts as evidence.
_Avoid_: As-of time, deadline

**Data flow**:
A sync, import, or connector process that can copy or recreate a Subject's data in another system.
_Avoid_: Pipeline, job

**Restore risk**:
A backup whose restore path is not blocked and could bring a Subject's deleted data back.
_Avoid_: Backup exposure

**Account tombstone**:
A deleted account's identity record that keeps only the stable `user_id` so retained records still resolve, with every direct identifier removed.
_Avoid_: Stub, placeholder account

### Policy

**Required treatment**:
The action policy demands for a Resource: DELETE, REDACT, ANONYMIZE, or RETAIN.
_Avoid_: Rule outcome, disposition
