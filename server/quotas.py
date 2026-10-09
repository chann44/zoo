"""Workspace quotas: how many sandboxes may run at once, their CPUs and memory together, and storage.

Each workspace gets a row when it is made, with the defaults from ZOO_DEFAULT_QUOTA_RUNNING_SANDBOXES,
ZOO_DEFAULT_QUOTA_CPUS, ZOO_DEFAULT_QUOTA_MEMORY_MB and ZOO_DEFAULT_QUOTA_STORAGE_GB (unset: no limit). Instance
admins (ADMIN_EMAILS) change a workspace's limits; members see them with their usage.

Creating or starting a sandbox checks the quota in the same transaction, after locking the workspace's row, so
requests that race each other take turns and can't together pass a limit."""

import os

from fastapi import HTTPException

from db.generated.query import EnsureWorkspaceQuotaParams, Querier, WorkspaceUsageRow
from server import sizes


def default(name: str) -> str | None:
    return os.environ.get(f"ZOO_DEFAULT_QUOTA_{name}") or None


RUNNING, CPUS, MEMORY, STORAGE = (default(n) for n in ("RUNNING_SANDBOXES", "CPUS", "MEMORY_MB", "STORAGE_GB"))


def ensure(db: Querier, workspace_id: str):
    """Gives a new workspace the default limits."""
    db.ensure_workspace_quota(
        EnsureWorkspaceQuotaParams(
            workspace_id=workspace_id,
            max_running_sandboxes=int(RUNNING) if RUNNING else None,
            max_cpus=float(CPUS) if CPUS else None,
            max_memory_mb=int(MEMORY) if MEMORY else None,
            max_storage_gb=int(STORAGE) if STORAGE else None,
        )
    )


def usage(db: Querier, workspace_id: str) -> WorkspaceUsageRow:
    row = db.workspace_usage(unsized_gb=sizes.UNSIZED_DISK_GB, workspace_id=workspace_id)
    assert row is not None
    return row


def storage_gb(row: WorkspaceUsageRow) -> float:
    return row.disk_gb + (row.profile_bytes + row.snapshot_bytes) / (1 << 30)


def check(db: Querier, workspace_id: str, size: sizes.Size, new: bool):
    """409 unless the workspace has room for one more running sandbox of `size`; `new` also counts its disk.
    Call inside the transaction that creates or starts it."""
    db.lock_workspace(id=workspace_id)
    quota = db.get_workspace_quota(workspace_id=workspace_id)
    if quota is None:
        return
    used = usage(db, workspace_id)
    disk = (size.disk_gb or sizes.UNSIZED_DISK_GB) if new else 0
    checks = [
        ("running sandboxes", quota.max_running_sandboxes, used.running + 1, used.running),
        ("CPUs", quota.max_cpus, used.cpus + size.cpus, used.cpus),
        ("memory (MB)", quota.max_memory_mb, used.memory_mb + size.memory_mb, used.memory_mb),
        ("storage (GB)", quota.max_storage_gb, storage_gb(used) + disk, round(storage_gb(used), 1)),
    ]
    for name, limit, wanted, now in checks:
        if limit is not None and wanted > limit:
            raise HTTPException(
                status_code=409, detail=f"the workspace's quota is {limit:g} {name}; it uses {now:g} already"
            )
