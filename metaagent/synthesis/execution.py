"""Execute generated statistical code in a real, networkless bubblewrap sandbox."""
from __future__ import annotations

import hashlib
import ctypes
import errno
import tempfile
import json
import os
from pathlib import Path
import resource
import selectors
import shutil
import signal
import stat
import subprocess
import sys
import time
import uuid


_SCMP_CMP_MASKED_EQ=7
_CLONE_THREAD=0x00010000


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _inventory(directory: Path, max_files: int, max_bytes: int) -> dict:
    files = {}
    total = 0
    entries = 0
    for path in directory.rglob('*'):
        entries += 1
        if entries > max_files * 4: raise ValueError('Generated output exceeds the directory/file budget')
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode):
            raise ValueError('Generated output contains a forbidden symbolic link')
        if path.is_dir():
            continue
        if not stat.S_ISREG(info.st_mode):
            raise ValueError('Generated output must contain only regular files')
        total += info.st_size
        if len(files) >= max_files or total > max_bytes:
            raise ValueError('Generated output exceeds the file/byte budget')
        files[str(path.relative_to(directory))] = {'bytes': info.st_size}
    return files


def _mount_runtime(command: list[str]) -> None:
    # Preserve interpreter paths because the venv's Python is an absolute symlink.
    # Parents are empty directories, never a bind of HOME or the project root.
    for path in (Path('/usr'), Path('/lib'), Path('/lib64'), Path('/bin'), Path(sys.base_prefix), Path(sys.prefix)):
        if path.exists():
            command.extend(['--ro-bind', str(path), str(path)])


class _ScmpArgCmp(ctypes.Structure):
    """One libseccomp argument comparison, read as (arg & datum_a) == datum_b."""
    _fields_=[('arg',ctypes.c_uint),('op',ctypes.c_int),('datum_a',ctypes.c_ulonglong),('datum_b',ctypes.c_ulonglong)]


def _process_filter():
    """Kernel filter: generated code cannot fork or spawn helpers, but may start a thread.

    A thread shares the sandbox address space and inherits every resource
    limit, so it opens no way out of the sandbox. Process creation stays
    closed: fork and vfork are refused, and clone is refused unless it
    carries CLONE_THREAD. clone3 answers ENOSYS so that glibc falls back to
    clone and meets the same rule; refusing clone3 outright would leave no
    way to start a thread, and the sandboxed libraries need one.
    """
    library=ctypes.CDLL('libseccomp.so.2',use_errno=True)
    library.seccomp_init.argtypes=[ctypes.c_uint32];library.seccomp_init.restype=ctypes.c_void_p
    library.seccomp_syscall_resolve_name.argtypes=[ctypes.c_char_p];library.seccomp_syscall_resolve_name.restype=ctypes.c_int
    library.seccomp_rule_add.argtypes=[ctypes.c_void_p,ctypes.c_uint32,ctypes.c_int,ctypes.c_uint]
    library.seccomp_export_bpf.argtypes=[ctypes.c_void_p,ctypes.c_int]
    library.seccomp_release.argtypes=[ctypes.c_void_p]
    context=library.seccomp_init(0x7fff0000)
    if not context:raise RuntimeError('Cannot initialize generated-code process filter')
    handle=tempfile.TemporaryFile()
    try:
        for syscall in ('fork','vfork'):
            number=library.seccomp_syscall_resolve_name(syscall.encode())
            if number>=0 and library.seccomp_rule_add(context,0x00050000|errno.EPERM,number,0)!=0:
                raise RuntimeError('Cannot constrain generated-code process creation')
        number=library.seccomp_syscall_resolve_name(b'clone3')
        if number>=0 and library.seccomp_rule_add(context,0x00050000|errno.ENOSYS,number,0)!=0:
            raise RuntimeError('Cannot constrain generated-code process creation')
        number=library.seccomp_syscall_resolve_name(b'clone')
        if number>=0:
            comparison=_ScmpArgCmp(arg=0,op=_SCMP_CMP_MASKED_EQ,datum_a=_CLONE_THREAD,datum_b=0)
            if library.seccomp_rule_add(context,0x00050000|errno.EPERM,number,1,comparison)!=0:
                raise RuntimeError('Cannot constrain generated-code process creation')
        if library.seccomp_export_bpf(context,handle.fileno())!=0:raise RuntimeError('Cannot export generated-code process filter')
        handle.seek(0)
        return handle
    except Exception:
        handle.close();raise
    finally:library.seccomp_release(context)


def execute_code(workspace: Path, code_path: Path, settings: dict, *, language: str = 'python') -> dict:
    """Return a host-created execution receipt; never fall back to host execution."""
    workspace = workspace.resolve()
    if language not in {'python', 'r'}:
        return {'status': 'failed', 'error': 'Only Python and R are supported'}
    if language == 'r' and shutil.which('Rscript') is None:
        return {'status': 'failed', 'error': 'Rscript is unavailable; use Python or supply an R-enabled runtime', 'recoverable': True}
    bwrap = shutil.which('bwrap')
    if not bwrap:
        return {'status': 'failed', 'error': 'bubblewrap is required; generated code was not executed', 'recoverable': True}
    if code_path.is_symlink() or not code_path.resolve().is_relative_to(workspace / 'code'):
        raise ValueError('Code must be a regular staged code file')
    execution_id = uuid.uuid4().hex
    output = workspace / 'executions' / execution_id
    output.mkdir(parents=True)
    timeout = min(120, max(1, float(settings.get('exec_timeout_s', 60))))
    max_output = min(32 * 1024 * 1024, int(settings.get('max_output_bytes', 16 * 1024 * 1024)))
    max_files = min(256, int(settings.get('max_output_files', 64)))
    log_cap = min(262144, int(settings.get('max_log_bytes', 65536)))
    memory = min(4 * 1024**3, int(settings.get('memory_bytes', 2 * 1024**3)))
    command = [bwrap, '--unshare-all', '--unshare-net', '--die-with-parent', '--new-session', '--cap-drop', 'ALL']
    _mount_runtime(command)
    command += ['--proc', '/proc', '--dev', '/dev', '--size', str(max_output), '--tmpfs', '/tmp', '--size', str(max_output), '--tmpfs', '/dev/shm', '--ro-bind', str(workspace / 'inputs'), '/inputs',
                '--ro-bind', str(workspace / 'sources'), '/sources', '--ro-bind', str(workspace / 'helpers'), '/helpers',
                '--ro-bind', str(workspace / 'analysis_plan.json'), '/analysis_plan.json',
                '--ro-bind', str(code_path.resolve()), '/analysis.' + ('py' if language == 'python' else 'R'),
                '--bind', str(output), '/work', '--chdir', '/work', '--clearenv']
    clean_env = {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8',
                 'PYTHONPATH': '/helpers', 'PYTHONNOUSERSITE': '1', 'PYTHONDONTWRITEBYTECODE': '1',
                 'MPLCONFIGDIR': '/tmp/matplotlib', 'OPENBLAS_NUM_THREADS': '1', 'OMP_NUM_THREADS': '1',
                 'MKL_NUM_THREADS': '1', 'NUMEXPR_NUM_THREADS': '1'}
    for key, value in clean_env.items():
        command += ['--setenv', key, value]
    command += [sys.executable, '/analysis.py'] if language == 'python' else [shutil.which('Rscript'), '/analysis.R']

    uid_threads = 0
    for status_path in Path('/proc').glob('[0-9]*/status'):
        try:
            status_text = status_path.read_text()
            fields = dict(line.split(':', 1) for line in status_text.splitlines() if ':' in line)
            if int(fields['Uid'].split()[0]) == os.getuid():
                uid_threads += int(fields.get('Threads', '1'))
        except (OSError, ValueError, KeyError):
            continue
    process_cap = uid_threads + 128

    def limits():
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
        cpu = max(1, int(timeout))
        resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu + 1))
        resource.setrlimit(resource.RLIMIT_FSIZE, (max_output, max_output))
        resource.setrlimit(resource.RLIMIT_NOFILE, (128, 128))
        resource.setrlimit(resource.RLIMIT_NPROC, (process_cap, process_cap))

    started = time.monotonic()
    receipt = {'execution_id': execution_id, 'status': 'failed', 'sandbox': 'bubblewrap', 'network': 'unshared',
               'code_sha256': file_sha(code_path), 'plan_sha256': file_sha(workspace / 'analysis_plan.json'),
               'input_sha256': file_sha(workspace / 'inputs/table.jsonl'), 'workspace_sha256': file_sha(workspace / 'workspace.json'), 'language': language,
               'limits': {'walltime_s': timeout, 'memory_bytes': memory, 'output_bytes': max_output, 'output_files': max_files, 'log_bytes': log_cap, 'host_uid_process_thread_cap': process_cap, 'host_uid_headroom': 128, 'generated_process_creation': 'seccomp_denied'},
               'output_directory': str(output)}
    chunks = {'stdout': bytearray(), 'stderr': bytearray()}
    process = None
    filter_file = None
    try:
        filter_file=_process_filter()
        command[1:1]=['--seccomp',str(filter_file.fileno())]
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   env={'PATH': '/usr/bin:/bin'}, start_new_session=True, preexec_fn=limits, close_fds=True, pass_fds=(filter_file.fileno(),))
        selector = selectors.DefaultSelector()
        for name, stream in (('stdout', process.stdout), ('stderr', process.stderr)):
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ, name)
        while selector.get_map() or process.poll() is None:
            if time.monotonic() - started > timeout:
                raise TimeoutError('Generated code exceeded the wall-time budget')
            _inventory(output, max_files, max_output)
            for key, _ in selector.select(.05):
                data = os.read(key.fileobj.fileno(), 8192)
                if not data:
                    selector.unregister(key.fileobj)
                    continue
                chunks[key.data].extend(data)
                if sum(map(len, chunks.values())) > log_cap:
                    raise ValueError('Generated code exceeded the stdout/stderr budget')
        process.wait(timeout=2)
        receipt['returncode'] = process.returncode
        if process.returncode != 0:
            raise RuntimeError('Generated code exited unsuccessfully; inspect the bounded stderr tail')
        inventory = _inventory(output, max_files, max_output)
        for name in inventory:
            inventory[name]['sha256'] = file_sha(output / name)
        receipt.update(status='complete', outputs=inventory)
    except Exception as exc:
        receipt.update(error={'type': type(exc).__name__, 'message': str(exc), 'recoverable': True})
    finally:
        if process is not None and process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=5)
        if filter_file is not None:filter_file.close()
        receipt['walltime_s'] = time.monotonic() - started
        for name, content in chunks.items():
            text = bytes(content[:log_cap]).decode('utf-8', errors='replace')
            receipt[name + '_tail'] = text[-12000:]
            receipt[name + '_sha256'] = hashlib.sha256(content).hexdigest()
        receipts = workspace / 'receipts'
        receipts.mkdir(exist_ok=True)
        (receipts / (execution_id + '.json')).write_text(json.dumps(receipt, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    return receipt
