# Issue Tracking - VM Power Attribution Project

## Status Legend
- [ ] Open
- [x] Closed
- [~] In Progress

---

## Phase 1.5 Issues

### [x] ISSUE-001: YOLO not running inside cgroup (Critical)
**Date**: 2026-02-06
**Status**: Closed
**Severity**: Critical

**Description**:
During Phase 1.5 test1, YOLO workload was not properly assigned to yolo.slice cgroup.
- Host logger showed RAPL 36-44W (YOLO running)
- cgroup logger showed yolo.slice CPU = 0% (not in cgroup)

**Root Cause**:
Script used `echo $$ > cgroup.procs` which only assigns the subshell PID.
When `yolo predict` runs, it spawns a new Python process outside the cgroup.

**Resolution**:
Modified `run_experiment_v3.sh` to use `systemd-run --scope --slice=yolo.slice` which properly contains all child processes.

**Verification**: Phase 1.5 test2 shows yolo.slice CPU at 97-104%.

---

### [x] ISSUE-002: Permission denied for data directory
**Date**: 2026-02-06
**Status**: Closed
**Severity**: Medium

**Description**:
Running experiment script failed with "Permission denied" when creating log directory.

**Root Cause**:
Previous experiment run with sudo created root-owned directories.

**Resolution**:
```bash
sudo chown -R joe:joe ~/vm-power-attribution/data/
```

---

### [x] ISSUE-003: Node.js showing high CPU in cgroup but low RAPL
**Date**: 2026-02-06
**Status**: Closed (Expected Behavior)
**Severity**: Low

**Description**:
Node.js solo phase shows 17-23% CPU in cgroup but only 7-9W RAPL.

**Analysis**:
This is expected behavior. Node.js is I/O bound (curl requests), so CPU utilization is measured but actual power consumption is low. The workload spends most time waiting for I/O rather than computing.

---

## Phase 2 Issues (Pending)

### [ ] ISSUE-004: VM power isolation
**Date**: -
**Status**: Open
**Severity**: TBD

**Description**:
Need to determine how to measure power per VM when VMs share physical hardware.

**Proposed Solutions**:
1. Use cgroup-based measurement (similar to Phase 1.5)
2. Implement power model based on resource utilization
3. Use RAPL + GPU power attribution based on VM activity

---

### [ ] ISSUE-005: Time synchronization for RPICT
**Date**: -
**Status**: Open
**Severity**: Medium

**Description**:
RPICT Raspberry Pi and Alienware may have clock drift, causing timestamp misalignment.

**Proposed Solutions**:
1. Use NTP synchronization on both devices
2. Use PTP for sub-millisecond accuracy
3. Use marker events for manual alignment

---

## Known Limitations

### LIM-001: RAPL DRAM always 0W
RAPL DRAM domain reports 0W on Alienware Aurora R12. This is a known limitation with some Intel platforms. DRAM power must be estimated from memory bandwidth.

### LIM-002: GPU power is system-wide
nvidia-smi reports total GPU power, not per-process. For accurate per-VM GPU attribution, need to use NVIDIA MPS or time-slice based estimation.

### LIM-003: PSU efficiency not measured
Wall power includes PSU losses (~10-20% inefficiency). Internal measurements (RAPL+GPU) are lower than wall power due to this loss.

---

## Feature Requests

### [ ] FR-001: Real-time power dashboard
Create a web-based dashboard for real-time power monitoring.

### [ ] FR-002: Automated experiment runner
Create a script that runs multiple iterations and calculates confidence intervals.

### [ ] FR-003: Energy cost calculator
Implement a calculator that converts energy measurements to actual cost in KRW/USD.

---

## Changelog

| Date | Issue | Action |
|------|-------|--------|
| 2026-02-06 | ISSUE-001 | Created, diagnosed root cause |
| 2026-02-06 | ISSUE-001 | Fixed with systemd-run |
| 2026-02-06 | ISSUE-001 | Verified in test2, closed |
| 2026-02-06 | ISSUE-002 | Created and closed |
| 2026-02-06 | ISSUE-003 | Created, marked as expected |
