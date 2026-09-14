"""Service-state I/O without following mutable directory or file links.

Callers pass absolute paths below their already selected, canonical root. POSIX
operations are relative to opened directory descriptors. Windows directory
handles deny delete sharing, keeping each ancestor in place until I/O finishes.
Neither branch resolves a workspace-controlled link into an authorized path.
"""

from __future__ import annotations

from contextlib import ExitStack
import json
import os
from pathlib import Path
import secrets
import stat
from typing import Any


class UnsafeStateError(OSError):
    """The state location is not an ordinary, unaliased file or directory."""


def _windows_open(path: Path, *, directory: bool, append: bool = False,
                  allow_reparse: bool = False) -> int:
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD,
                                  wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL

    class AttributeTag(ctypes.Structure):
        _fields_ = [("attributes", wintypes.DWORD), ("tag", wintypes.DWORD)]

    kernel.GetFileInformationByHandleEx.argtypes = [
        wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD,
    ]
    kernel.GetFileInformationByHandleEx.restype = wintypes.BOOL
    # GENERIC_READ / FILE_APPEND_DATA|FILE_READ_ATTRIBUTES; READ|WRITE sharing
    # (never DELETE); OPEN_EXISTING / OPEN_ALWAYS; OPEN_REPARSE_POINT|BACKUP_SEMANTICS.
    # Attributes-only directory handles do not participate in delete sharing.
    handle = kernel.CreateFileW(str(path), 0x84 if append else 0x80000000,
                                3, None, 4 if append else 3, 0x02200000, None)
    if handle == wintypes.HANDLE(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        info = AttributeTag()
        if not kernel.GetFileInformationByHandleEx(handle, 9, ctypes.byref(info),
                                                   ctypes.sizeof(info)):
            raise ctypes.WinError(ctypes.get_last_error())
        if ((info.attributes & 0x400 and not allow_reparse)
                or bool(info.attributes & 0x10) != directory):
            raise UnsafeStateError("linked or non-regular state location")
        return handle
    except BaseException:
        kernel.CloseHandle(handle)
        raise


def _windows_close(handle: int) -> None:
    import ctypes
    from ctypes import wintypes

    close = ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle
    close.argtypes = [wintypes.HANDLE]
    close.restype = wintypes.BOOL
    close(handle)


def canonical_directory(path: Path) -> Path:
    """Resolve one caller-selected directory before protected children are added."""
    selected = Path(path).expanduser().absolute()
    if os.name != "nt":
        return selected.resolve()

    import ctypes
    from ctypes import wintypes
    import struct

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetFileAttributesW.argtypes = [wintypes.LPCWSTR]
    kernel.GetFileAttributesW.restype = wintypes.DWORD
    kernel.DeviceIoControl.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPVOID,
                                      wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD,
                                      ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
    kernel.DeviceIoControl.restype = wintypes.BOOL

    def link_target(link: Path) -> Path:
        handle = _windows_open(link, directory=True, allow_reparse=True)
        try:
            buffer = ctypes.create_string_buffer(16 * 1024)
            returned = wintypes.DWORD()
            if not kernel.DeviceIoControl(handle, 0x000900A8, None, 0, buffer,
                                          len(buffer), ctypes.byref(returned), None):
                raise ctypes.WinError(ctypes.get_last_error())
            raw = buffer.raw[: returned.value]
        finally:
            _windows_close(handle)
        tag = struct.unpack_from("<I", raw)[0]
        if tag == 0xA0000003:  # IO_REPARSE_TAG_MOUNT_POINT
            offset, length = struct.unpack_from("<HH", raw, 8)
            start, relative = 16 + offset, False
        elif tag == 0xA000000C:  # IO_REPARSE_TAG_SYMLINK
            offset, length = struct.unpack_from("<HH", raw, 8)
            start = 20 + offset
            relative = bool(struct.unpack_from("<I", raw, 16)[0] & 1)
        else:
            raise UnsafeStateError("unsupported selected-directory reparse point")
        target = raw[start : start + length].decode("utf-16-le")
        if relative:
            return link.parent / target
        if target.startswith("\\??\\UNC\\"):
            target = "\\\\" + target[8:]
        elif target.startswith("\\??\\"):
            target = target[4:]
        return Path(target)

    def resolve_directory(candidate: Path, seen: set[str]) -> Path:
        current = Path(candidate.anchor)
        for part in candidate.parts[1:]:
            current = current / part
            attributes = kernel.GetFileAttributesW(str(current))
            if attributes == 0xFFFFFFFF:
                raise ctypes.WinError(ctypes.get_last_error())
            if attributes & 0x400:
                marker = os.path.normcase(str(current))
                if marker in seen or len(seen) >= 64:
                    raise UnsafeStateError("selected-directory link cycle")
                seen.add(marker)
                current = resolve_directory(link_target(current).absolute(), seen)
        return current

    resolved = resolve_directory(selected, set())
    attributes = kernel.GetFileAttributesW(str(resolved))
    if attributes == 0xFFFFFFFF:
        raise ctypes.WinError(ctypes.get_last_error())
    if not attributes & 0x10 or attributes & 0x400:
        raise UnsafeStateError("selected path is not an ordinary directory")
    return resolved


class StateDirectory:
    """Pin the ancestry once and use it for every operation in this context."""

    def __init__(self, path: Path, *, create: bool = False):
        self.path = Path(path)
        if not self.path.is_absolute() or ".." in self.path.parts:
            raise UnsafeStateError("state directory must be an absolute canonical path")
        self.create = create
        self.fd: int | None = None
        self._stack = ExitStack()

    def __enter__(self):
        try:
            if os.name == "nt":
                current = Path(self.path.anchor)
                self._stack.callback(_windows_close, _windows_open(current, directory=True))
                for part in self.path.parts[1:]:
                    current = current / part
                    if self.create:
                        try:
                            os.mkdir(current, 0o700)
                        except FileExistsError:
                            pass
                    self._stack.callback(_windows_close, _windows_open(current, directory=True))
            else:
                flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
                self.fd = os.open(self.path.anchor, flags)
                self._stack.callback(os.close, self.fd)
                for part in self.path.parts[1:]:
                    if self.create:
                        try:
                            os.mkdir(part, 0o700, dir_fd=self.fd)
                        except FileExistsError:
                            pass
                    self.fd = os.open(part, flags, dir_fd=self.fd)
                    self._stack.callback(os.close, self.fd)
            return self
        except BaseException:
            self._stack.close()
            raise

    def __exit__(self, *exc):
        return self._stack.__exit__(*exc)

    def _name(self, name: str):
        if not name or name in {".", ".."} or "/" in name or "\\" in name or ":" in name:
            raise UnsafeStateError("state filename must be one directory entry")
        return self.path / name if os.name == "nt" else name

    def _kwargs(self) -> dict[str, int]:
        return {} if os.name == "nt" else {"dir_fd": self.fd}

    @staticmethod
    def _regular(info) -> None:
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or getattr(info, "st_file_attributes", 0) & 0x400):
            raise UnsafeStateError("linked or non-regular state file")

    def check_file(self, name: str) -> None:
        try:
            info = os.stat(self._name(name), follow_symlinks=False, **self._kwargs())
        except FileNotFoundError:
            return
        self._regular(info)

    def read_bytes(self, name: str, *, limit: int | None = None) -> bytes:
        if os.name == "nt":
            import msvcrt

            handle = _windows_open(self._name(name), directory=False)
            try:
                descriptor = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
            except BaseException:
                _windows_close(handle)
                raise
        else:
            descriptor = os.open(self._name(name), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                                 **self._kwargs())
        with os.fdopen(descriptor, "rb") as source:
            self._regular(os.fstat(source.fileno()))
            data = source.read() if limit is None else source.read(limit + 1)
        if limit is not None and len(data) > limit:
            raise ValueError("state document exceeds the size limit")
        return data

    def read_json(self, name: str, *, limit: int | None = None) -> Any:
        return json.loads(self.read_bytes(name, limit=limit))

    def write_bytes(self, name: str, data: bytes) -> None:
        self.check_file(name)
        temporary = f".{name}.{secrets.token_hex(16)}.tmp"
        descriptor = os.open(self._name(temporary), os.O_CREAT | os.O_EXCL | os.O_WRONLY
                             | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0),
                             0o600, **self._kwargs())
        try:
            with os.fdopen(descriptor, "wb") as destination:
                destination.write(data)
                destination.flush()
                os.fsync(destination.fileno())
            if os.name == "nt":
                os.replace(self._name(temporary), self._name(name))
            else:
                os.replace(temporary, name, src_dir_fd=self.fd, dst_dir_fd=self.fd)
                os.fsync(self.fd)
            # Never chmod the final path: it could already have been replaced.
        finally:
            try:
                os.unlink(self._name(temporary), **self._kwargs())
            except FileNotFoundError:
                pass

    def write_json(self, name: str, value: Any) -> None:
        self.write_bytes(name, json.dumps(value, ensure_ascii=False, sort_keys=True,
                                         separators=(",", ":"), allow_nan=False).encode("utf-8"))

    def append_bytes(self, name: str, data: bytes) -> None:
        if os.name == "nt":
            import msvcrt

            handle = _windows_open(self._name(name), directory=False, append=True)
            try:
                descriptor = msvcrt.open_osfhandle(handle, os.O_WRONLY | os.O_APPEND | os.O_BINARY)
            except BaseException:
                _windows_close(handle)
                raise
        else:
            descriptor = os.open(self._name(name), os.O_CREAT | os.O_WRONLY | os.O_APPEND
                                 | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, **self._kwargs())
        with os.fdopen(descriptor, "ab") as destination:
            self._regular(os.fstat(destination.fileno()))
            destination.write(data)
            destination.flush()
            os.fsync(destination.fileno())

    def names(self) -> list[str]:
        return sorted(os.listdir(self.path if os.name == "nt" else self.fd))

    def unlink(self, name: str) -> None:
        self.check_file(name)
        os.unlink(self._name(name), **self._kwargs())


def read_json(path: Path, *, limit: int | None = None) -> Any:
    with StateDirectory(path.parent) as directory:
        return directory.read_json(path.name, limit=limit)


def write_json(path: Path, value: Any) -> None:
    with StateDirectory(path.parent, create=True) as directory:
        directory.write_json(path.name, value)


def check_target(path: Path) -> None:
    with StateDirectory(path.parent, create=True) as directory:
        directory.check_file(path.name)
