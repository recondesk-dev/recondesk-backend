"""Automated tests for ReconDesk v1.5.1 Aurora Snapshot Deployment Gate.

Covers all 7 operational and failure scenarios:
1. Snapshot missing -> invokes create-db-cluster-snapshot -> polls through eventual consistency -> available (PASS)
2. Snapshot already exists and is available -> reuses existing without creating (PASS)
3. Snapshot already creating -> waits for available without creating (PASS)
4. Snapshot in terminal failure state ('failed') -> halts immediately with error (PASS)
5. Snapshot belongs to different cluster -> halts immediately with security error (PASS)
6. AWS create error (e.g. AccessDenied) -> fails immediately (PASS)
7. AWS describe error (e.g. AuthFailure) -> fails immediately (PASS)
"""

import json
import os
import stat
import subprocess
import tempfile
from pathlib import Path
import pytest


SCRIPT_PATH = Path(__file__).resolve().parent.parent.parent / "scripts" / "deploy_v1_5_1_production.sh"


def run_gate_with_mock_aws(responses, env_overrides=None):
    """Run deploy_v1_5_1_production.sh --test-snapshot-gate with a stateful mock aws binary."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        state_file = tmp_path / "mock_state.json"
        log_file = tmp_path / "calls.log"

        state_data = {
            "responses": responses,
            "call_index": 0,
        }
        state_file.write_text(json.dumps(state_data))

        mock_aws = tmp_path / "aws"
        mock_aws_code = f"""#!/usr/bin/env python3
import sys
import json
from pathlib import Path

state_file = Path("{state_file}")
log_file = Path("{log_file}")

with open(log_file, "a") as f:
    f.write(" ".join(sys.argv[1:]) + "\\n")

with open(state_file, "r") as f:
    state = json.load(f)

idx = state["call_index"]
responses = state["responses"]

if idx >= len(responses):
    resp = responses[-1]
else:
    resp = responses[idx]
    state["call_index"] = idx + 1
    with open(state_file, "w") as f:
        json.dump(state, f)

exit_code = resp.get("code", 0)
stdout = resp.get("stdout", "")
stderr = resp.get("stderr", "")

if stdout:
    sys.stdout.write(stdout if stdout.endswith("\\n") else stdout + "\\n")
if stderr:
    sys.stderr.write(stderr if stderr.endswith("\\n") else stderr + "\\n")
sys.exit(exit_code)
"""
        mock_aws.write_text(mock_aws_code)
        mock_aws.chmod(mock_aws.stat().st_mode | stat.S_IEXEC)

        env = os.environ.copy()
        env["PATH"] = f"{tmpdir}:{env['PATH']}"
        env["SNAPSHOT_POLL_INTERVAL"] = "0.01"  # Fast polling for test suite
        env["SNAPSHOT_MAX_ATTEMPTS"] = "20"
        if env_overrides:
            env.update(env_overrides)

        res = subprocess.run(
            ["bash", str(SCRIPT_PATH), "--test-snapshot-gate"],
            env=env,
            capture_output=True,
            text=True,
        )

        calls = log_file.read_text().splitlines() if log_file.exists() else []
        return res, calls


def test_scenario1_missing_then_created_then_available():
    """Missing snapshot: initiates creation, retries through propagation delay, succeeds when available."""
    responses = [
        # Initial check: not found
        {
            "code": 254,
            "stderr": "An error occurred (DBClusterSnapshotNotFoundFault) when calling DescribeDBClusterSnapshots: not found",
        },
        # Create call: succeeds
        {
            "code": 0,
            "stdout": json.dumps({"DBClusterSnapshot": {"Status": "creating", "DBClusterSnapshotIdentifier": "recondesk-pre-v1-5-1"}}),
        },
        # Wait attempt 1: eventual consistency (still returns not found)
        {
            "code": 254,
            "stderr": "DBClusterSnapshotNotFoundFault: DBClusterSnapshot not found",
        },
        # Wait attempt 2: snapshot appearing in creating state
        {
            "code": 0,
            "stdout": json.dumps({
                "DBClusterSnapshots": [{
                    "DBClusterSnapshotIdentifier": "recondesk-pre-v1-5-1",
                    "DBClusterIdentifier": "recondesk",
                    "Status": "creating",
                    "PercentProgress": 45,
                }]
            }),
        },
        # Wait attempt 3: snapshot available
        {
            "code": 0,
            "stdout": json.dumps({
                "DBClusterSnapshots": [{
                    "DBClusterSnapshotIdentifier": "recondesk-pre-v1-5-1",
                    "DBClusterIdentifier": "recondesk",
                    "Status": "available",
                    "PercentProgress": 100,
                }]
            }),
        },
    ]

    res, calls = run_gate_with_mock_aws(responses)
    assert res.returncode == 0, f"Expected success but got {res.returncode}. Output:\n{res.stdout}\n{res.stderr}"
    assert "Initiating creation on cluster 'recondesk'" in res.stdout
    assert "Snapshot creation initiated successfully." in res.stdout
    assert "Snapshot not yet registered in AWS RDS (propagation delay" in res.stdout
    assert "confirmed AVAILABLE and verified" in res.stdout

    # Verify create was called with correct cluster, snapshot id, and region
    create_calls = [c for c in calls if "create-db-cluster-snapshot" in c]
    assert len(create_calls) == 1
    assert "--db-cluster-identifier recondesk" in create_calls[0]
    assert "--db-cluster-snapshot-identifier recondesk-pre-v1-5-1" in create_calls[0]
    assert "--region ap-south-1" in create_calls[0]


def test_scenario2_already_available_reuses_without_create():
    """Snapshot already available: reuses snapshot and NEVER invokes create-db-cluster-snapshot."""
    responses = [
        {
            "code": 0,
            "stdout": json.dumps({
                "DBClusterSnapshots": [{
                    "DBClusterSnapshotIdentifier": "recondesk-pre-v1-5-1",
                    "DBClusterIdentifier": "recondesk",
                    "Status": "available",
                    "PercentProgress": 100,
                }]
            }),
        }
    ]

    res, calls = run_gate_with_mock_aws(responses)
    assert res.returncode == 0, f"Expected success, got {res.returncode}:\n{res.stdout}\n{res.stderr}"
    assert "already exists and is confirmed AVAILABLE for cluster 'recondesk'. Reusing existing snapshot." in res.stdout
    assert not any("create-db-cluster-snapshot" in c for c in calls), "create-db-cluster-snapshot should NOT be called"


def test_scenario3_already_creating_waits_without_create():
    """Snapshot in creating state: waits for available and NEVER invokes create-db-cluster-snapshot."""
    responses = [
        # Initial check: already creating
        {
            "code": 0,
            "stdout": json.dumps({
                "DBClusterSnapshots": [{
                    "DBClusterSnapshotIdentifier": "recondesk-pre-v1-5-1",
                    "DBClusterIdentifier": "recondesk",
                    "Status": "creating",
                    "PercentProgress": 70,
                }]
            }),
        },
        # Poll 1: available
        {
            "code": 0,
            "stdout": json.dumps({
                "DBClusterSnapshots": [{
                    "DBClusterSnapshotIdentifier": "recondesk-pre-v1-5-1",
                    "DBClusterIdentifier": "recondesk",
                    "Status": "available",
                    "PercentProgress": 100,
                }]
            }),
        },
    ]

    res, calls = run_gate_with_mock_aws(responses)
    assert res.returncode == 0, f"Expected success, got {res.returncode}:\n{res.stdout}\n{res.stderr}"
    assert "already exists in progress (creating, 70%). Waiting for completion..." in res.stdout
    assert "confirmed AVAILABLE and verified" in res.stdout
    assert not any("create-db-cluster-snapshot" in c for c in calls)


def test_scenario4_failed_state_halts_immediately():
    """Snapshot in 'failed' status: halts immediately with non-zero exit code."""
    responses = [
        {
            "code": 0,
            "stdout": json.dumps({
                "DBClusterSnapshots": [{
                    "DBClusterSnapshotIdentifier": "recondesk-pre-v1-5-1",
                    "DBClusterIdentifier": "recondesk",
                    "Status": "failed",
                }]
            }),
        }
    ]

    res, calls = run_gate_with_mock_aws(responses)
    assert res.returncode != 0
    assert "terminal failure state: 'failed'" in res.stderr
    assert not any("create-db-cluster-snapshot" in c for c in calls)


def test_scenario5_cluster_mismatch_halts_with_security_error():
    """Snapshot exists on a different cluster: halts immediately with security error."""
    responses = [
        {
            "code": 0,
            "stdout": json.dumps({
                "DBClusterSnapshots": [{
                    "DBClusterSnapshotIdentifier": "recondesk-pre-v1-5-1",
                    "DBClusterIdentifier": "foreign-unauthorized-cluster",
                    "Status": "available",
                }]
            }),
        }
    ]

    res, calls = run_gate_with_mock_aws(responses)
    assert res.returncode != 0
    assert "SECURITY VIOLATION: Snapshot 'recondesk-pre-v1-5-1' belongs to cluster 'foreign-unauthorized-cluster'" in res.stderr
    assert not any("create-db-cluster-snapshot" in c for c in calls)


def test_scenario6_create_error_fails_immediately():
    """aws rds create-db-cluster-snapshot returns an error: script fails immediately."""
    responses = [
        # Initial describe: not found
        {
            "code": 254,
            "stderr": "DBClusterSnapshotNotFoundFault: snapshot not found",
        },
        # Create call: AccessDenied error
        {
            "code": 254,
            "stderr": "An error occurred (AccessDeniedException) when calling CreateDBClusterSnapshot: User is not authorized",
        },
    ]

    res, calls = run_gate_with_mock_aws(responses)
    assert res.returncode != 0
    assert "Failed to initiate Aurora cluster snapshot" in res.stderr
    assert "AccessDeniedException" in res.stderr


def test_scenario7_describe_unexpected_aws_error_fails_immediately():
    """aws rds describe returns unexpected error (e.g. AuthFailure): script fails immediately without creating."""
    responses = [
        {
            "code": 254,
            "stderr": "An error occurred (AuthFailure) when calling DescribeDBClusterSnapshots: AWS was not able to validate credentials",
        }
    ]

    res, calls = run_gate_with_mock_aws(responses)
    assert res.returncode != 0
    assert "AWS error checking snapshot" in res.stderr
    assert not any("create-db-cluster-snapshot" in c for c in calls)


def run_parse_snapshot_info(raw: str, exit_code: int) -> tuple[str, str, str, str, str]:
    """Helper to run the exact parse_snapshot_info logic."""
    proc = subprocess.run(
        ["bash", "-c", f"""
source "{SCRIPT_PATH}"
parse_snapshot_info "$1" "$2"
""", "bash", raw, str(exit_code)],
        capture_output=True,
        text=True,
    )
    tokens = proc.stdout.strip().split()
    assert len(tokens) == 5, f"Expected 5 tokens, got: {proc.stdout} (err: {proc.stderr})"
    return tuple(tokens)


def test_parse_snapshot_info_empty_list():
    raw = json.dumps({"DBClusterSnapshots": []})
    exists, status, cluster, prog, err = run_parse_snapshot_info(raw, 0)
    assert exists == "false"
    assert status == "NONE"
    assert err == "NONE"


def test_parse_snapshot_info_not_found_fault():
    raw = "An error occurred (DBClusterSnapshotNotFoundFault) when calling DescribeDBClusterSnapshots: not found"
    exists, status, cluster, prog, err = run_parse_snapshot_info(raw, 254)
    assert exists == "false"
    assert status == "NOT_FOUND"
    assert err == "NOT_FOUND"


def test_parse_snapshot_info_available():
    raw = json.dumps({
        "DBClusterSnapshots": [{
            "Status": "available",
            "DBClusterIdentifier": "recondesk",
            "PercentProgress": 100,
        }]
    })
    exists, status, cluster, prog, err = run_parse_snapshot_info(raw, 0)
    assert exists == "true"
    assert status == "available"
    assert cluster == "recondesk"
    assert prog == "100"
    assert err == "NONE"


def test_parse_snapshot_info_aws_api_error():
    raw = "An error occurred (AccessDeniedException) when calling DescribeDBClusterSnapshots: User not authorized"
    exists, status, cluster, prog, err = run_parse_snapshot_info(raw, 254)
    assert exists == "error"
    assert status == "AWS_API_ERROR"
    assert "AccessDeniedException" in err

