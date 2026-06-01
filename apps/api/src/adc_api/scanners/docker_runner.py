from __future__ import annotations

import asyncio


async def docker_available() -> bool:
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker", "version",
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
        return proc.returncode == 0
    except (FileNotFoundError, OSError):
        return False


async def run_in_container(
    *, image: str, cmd: list[str], host_dir: str, timeout: int, network: str = "none"
) -> str:
    """Run `image` with the host dir mounted read-only; return stdout.

    The code is mounted read-only and is never executed (scanners do static analysis), so a scanner
    that needs to fetch its rules (Semgrep) may opt into network access via `network="bridge"`;
    fully-offline scanners (Bandit) keep the default `network="none"` sandbox.

    Scanners write SARIF to stdout and may exit non-zero when findings exist, so the exit code is
    intentionally ignored — the caller parses stdout (unparseable output => no findings).
    """
    args = [
        "docker", "run", "--rm", f"--network={network}",
        "-v", f"{host_dir}:/src:ro", "-w", "/src", image, *cmd,
    ]
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        proc.kill()
        raise
    return out.decode("utf-8", "replace")
