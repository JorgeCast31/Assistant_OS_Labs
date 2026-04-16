"""Best-effort OS-level hardening helpers for worker subprocesses."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
import socket
import subprocess
from urllib import request as urllib_request


def default_creationflags() -> int:
    flags = 0
    flags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    flags |= getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)
    flags |= getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return flags


def apply_os_process_hardening(process: subprocess.Popen[str], *, memory_limit_bytes: int) -> dict:
    """Apply the strongest reliable OS-level controls available."""
    result = {
        "applied": False,
        "platform": os.name,
        "memory_limit_bytes": memory_limit_bytes,
        "priority": "below_normal",
        "job_object": False,
        "job_handle": 0,
        "affinity": "",
        "detail": "OS-level hardening unavailable.",
    }
    if os.name != "nt":
        result["detail"] = "Windows Job Objects are unavailable on this platform."
        return result

    kernel32 = ctypes.windll.kernel32
    PROCESS_SET_QUOTA = 0x0100
    PROCESS_SET_INFORMATION = 0x0200
    PROCESS_TERMINATE = 0x0001
    JobObjectExtendedLimitInformation = 9
    JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x00000100
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
    JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION = 0x00000400

    class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]

    class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    process_handle = kernel32.OpenProcess(PROCESS_SET_QUOTA | PROCESS_SET_INFORMATION | PROCESS_TERMINATE, False, process.pid)
    if not process_handle:
        result["detail"] = "OpenProcess failed; subprocess still runs with logical controls."
        return result

    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        kernel32.CloseHandle(process_handle)
        result["detail"] = "CreateJobObject failed; subprocess still runs with logical controls."
        return result

    try:
        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = (
            JOB_OBJECT_LIMIT_PROCESS_MEMORY
            | JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            | JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION
        )
        info.ProcessMemoryLimit = memory_limit_bytes
        ok = kernel32.SetInformationJobObject(
            job,
            JobObjectExtendedLimitInformation,
            ctypes.byref(info),
            ctypes.sizeof(info),
        )
        if not ok:
            result["detail"] = "SetInformationJobObject failed; subprocess still runs with logical controls."
            return result
        assigned = kernel32.AssignProcessToJobObject(job, process_handle)
        if not assigned:
            result["detail"] = "AssignProcessToJobObject failed; subprocess still runs with logical controls."
            return result
        affinity_mask = ctypes.c_size_t(1)
        system_mask = ctypes.c_size_t()
        if kernel32.GetProcessAffinityMask(process_handle, ctypes.byref(affinity_mask), ctypes.byref(system_mask)):
            chosen = affinity_mask.value & -affinity_mask.value
            if chosen:
                kernel32.SetProcessAffinityMask(process_handle, chosen)
                result["affinity"] = str(chosen)
        result["applied"] = True
        result["job_object"] = True
        result["job_handle"] = int(job)
        result["detail"] = "Applied Windows Job Object memory bound, kill-on-close, and best-effort affinity restriction."
        return result
    finally:
        kernel32.CloseHandle(process_handle)


def install_network_deny_hooks() -> None:
    """Install deny-by-default network hooks inside the worker subprocess."""

    def _deny(*_args, **_kwargs):
        raise RuntimeError("network denied by worker secure execution layer")

    socket.socket = _deny  # type: ignore[assignment]
    socket.create_connection = _deny  # type: ignore[assignment]
    socket.getaddrinfo = _deny  # type: ignore[assignment]
    urllib_request.urlopen = _deny  # type: ignore[assignment]
