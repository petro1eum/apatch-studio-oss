"""Process-local OS change notices; no content reads, disk cache or authority.

Stat tuples alone cannot certify unchanged contents on a coarse filesystem.
Linux watches directories, macOS uses vnode events, and Windows uses one
overlapped directory handle. Resources are released with the owning index.
Lost notifications require explicit cache reconstruction, never silent reuse.
"""
from __future__ import annotations

import ctypes
import os
from pathlib import Path
import select
import struct
import sys
import weakref


class LedgerEvents:
    def __init__(self, root: Path):
        self.root = Path(root)
        if sys.platform.startswith("linux"):
            self._watcher = _Inotify(self.root)
        elif sys.platform == "darwin":
            self._watcher = _Kqueue()
        elif sys.platform == "win32":
            self._watcher = _WindowsChanges(self.root)
        else:
            raise RuntimeError("ledger_change_notifications_unavailable")

    def changed(self, paths: list[Path]) -> set[str]:
        self._watcher.prepare(paths)
        notices = self._watcher.drain()
        if notices is None:
            raise RuntimeError("ledger_change_notifications_lost")
        self._watcher.prepare(paths)
        # A directory replacement invalidates its known descendants. Ordinary
        # writes name one object and never reread its unchanged neighbours.
        return {str(path) for path in paths
                if any(path == changed or changed in path.parents for changed in notices)}


class _Inotify:
    _MASK = 0x00000002 | 0x00000004 | 0x00000008 | 0x000000C0 | 0x00000300 | 0x00000C00

    def __init__(self, root: Path):
        self.root = root
        self._lib = ctypes.CDLL(None, use_errno=True)
        self._lib.inotify_init1.argtypes = [ctypes.c_int]
        self._lib.inotify_init1.restype = ctypes.c_int
        self._lib.inotify_add_watch.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_uint32]
        self._lib.inotify_add_watch.restype = ctypes.c_int
        self._lib.inotify_rm_watch.argtypes = [ctypes.c_int, ctypes.c_int]
        self._lib.inotify_rm_watch.restype = ctypes.c_int
        self._fd = self._lib.inotify_init1(os.O_NONBLOCK | os.O_CLOEXEC)
        if self._fd < 0:
            raise RuntimeError("ledger_change_notifications_unavailable")
        self._cleanup = weakref.finalize(self, os.close, self._fd)
        self._directories: dict[Path, tuple[int, tuple[int, int]]] = {}
        self._descriptors: dict[int, Path] = {}
        self._pending: set[Path] = set()

    def prepare(self, paths):
        directories = {self.root, *(path.parent for path in paths)}
        for directory in set(self._directories) - directories:
            descriptor, _ = self._directories.pop(directory)
            self._descriptors.pop(descriptor, None)
            self._lib.inotify_rm_watch(self._fd, descriptor)
        for directory in directories:
            stat = directory.stat()
            identity = (stat.st_dev, stat.st_ino)
            previous = self._directories.get(directory)
            if previous is not None and previous[1] == identity:
                continue
            if previous is not None:
                self._pending.add(directory)
                self._descriptors.pop(previous[0], None)
                self._lib.inotify_rm_watch(self._fd, previous[0])
            descriptor = self._lib.inotify_add_watch(self._fd, os.fsencode(directory), self._MASK)
            if descriptor < 0:
                raise RuntimeError("ledger_change_notifications_unavailable")
            self._directories[directory] = (descriptor, identity)
            self._descriptors[descriptor] = directory

    def drain(self):
        changed, self._pending = self._pending, set()
        lost = False
        # A perpetually active writer cannot keep a refresh blocked forever.
        for _batch in range(64):
            try:
                raw = os.read(self._fd, 65536)
            except BlockingIOError:
                break
            except InterruptedError:
                continue
            if not raw:
                return None
            position = 0
            while position < len(raw):
                descriptor, mask, _, length = struct.unpack_from("iIII", raw, position)
                position += 16
                name = raw[position:position + length].split(b"\0", 1)[0]
                position += length
                if mask & 0x00004000:  # IN_Q_OVERFLOW: identity is no longer known.
                    lost = True
                directory = self._descriptors.get(descriptor)
                if directory is None:
                    continue
                changed.add(directory / os.fsdecode(name) if name else directory)
                if mask & 0x00008000:  # IN_IGNORED: re-register on the next refresh.
                    self._descriptors.pop(descriptor, None)
                    self._directories.pop(directory, None)
        else:
            return None
        return None if lost else changed


class _Kqueue:
    def __init__(self):
        self._queue = select.kqueue()
        self._files: dict[Path, int] = {}
        self._descriptors: dict[int, Path] = {}
        self._pending: set[Path] = set()
        def cleanup(queue, files):
            queue.close()
            for descriptor in files.values():
                os.close(descriptor)
        self._cleanup = weakref.finalize(self, cleanup, self._queue, self._files)

    def prepare(self, paths):
        for deleted in set(self._files) - set(paths):
            descriptor = self._files.pop(deleted)
            self._descriptors.pop(descriptor, None)
            os.close(descriptor)
        for path in paths:
            if path in self._files:
                continue
            try:
                descriptor = os.open(path, os.O_EVTONLY | os.O_CLOEXEC)
            except OSError as error:
                raise RuntimeError("ledger_change_notifications_unavailable") from error
            change = select.kevent(descriptor, filter=select.KQ_FILTER_VNODE,
                flags=select.KQ_EV_ADD | select.KQ_EV_CLEAR,
                fflags=select.KQ_NOTE_WRITE | select.KQ_NOTE_EXTEND | select.KQ_NOTE_ATTRIB |
                       select.KQ_NOTE_DELETE | select.KQ_NOTE_RENAME | select.KQ_NOTE_REVOKE)
            try:
                self._queue.control([change], 0, 0)
            except OSError as error:
                os.close(descriptor)
                raise RuntimeError("ledger_change_notifications_unavailable") from error
            self._files[path] = descriptor
            self._descriptors[descriptor] = path

    def drain(self):
        changed, self._pending = self._pending, set()
        for _batch in range(64):
            events = self._queue.control([], 4096, 0)
            if not events:
                return changed
            for event in events:
                path = self._descriptors.get(event.ident)
                if path is None:
                    continue
                if event.flags & select.KQ_EV_ERROR:
                    return None
                changed.add(path)
                if event.fflags & (select.KQ_NOTE_DELETE | select.KQ_NOTE_RENAME |
                                   select.KQ_NOTE_REVOKE):
                    self._files.pop(path, None)
                    self._descriptors.pop(event.ident, None)
                    os.close(event.ident)
        return None


class _WindowsChanges:
    def __init__(self, root: Path):
        from ctypes import wintypes
        self.root = root
        self._api = ctypes.WinDLL("kernel32", use_last_error=True)
        class Overlapped(ctypes.Structure):
            _fields_ = [("internal", ctypes.c_size_t), ("internal_high", ctypes.c_size_t),
                        ("offset", wintypes.DWORD), ("offset_high", wintypes.DWORD),
                        ("event", wintypes.HANDLE)]
        self._overlap = Overlapped()
        self._buffer = ctypes.create_string_buffer(65536)
        pointer = ctypes.c_void_p
        self._api.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                         pointer, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        self._api.CreateFileW.restype = wintypes.HANDLE
        self._api.ReadDirectoryChangesW.argtypes = [wintypes.HANDLE, pointer, wintypes.DWORD,
            wintypes.BOOL, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), pointer, pointer]
        self._api.ReadDirectoryChangesW.restype = wintypes.BOOL
        self._api.GetOverlappedResult.argtypes = [wintypes.HANDLE, pointer,
                                                 ctypes.POINTER(wintypes.DWORD), wintypes.BOOL]
        self._api.GetOverlappedResult.restype = wintypes.BOOL
        self._api.CancelIoEx.argtypes = [wintypes.HANDLE, pointer]
        self._api.CancelIoEx.restype = wintypes.BOOL
        self._api.CloseHandle.argtypes = [wintypes.HANDLE]
        self._api.CloseHandle.restype = wintypes.BOOL
        self._handle = self._api.CreateFileW(str(root), 1, 7, None, 3, 0x42000000, None)
        if self._handle == ctypes.c_void_p(-1).value:
            raise RuntimeError("ledger_change_notifications_unavailable")
        def cleanup(api, handle, buffer, overlap):
            api.CancelIoEx(handle, ctypes.byref(overlap))
            transferred = wintypes.DWORD()
            api.GetOverlappedResult(handle, ctypes.byref(overlap), ctypes.byref(transferred), True)
            api.CloseHandle(handle)
        self._cleanup = weakref.finalize(self, cleanup, self._api, self._handle,
                                         self._buffer, self._overlap)
        self._arm()

    def _arm(self):
        if not self._api.ReadDirectoryChangesW(self._handle, self._buffer, len(self._buffer),
                True, 0x1F, None, ctypes.byref(self._overlap), None):
            raise RuntimeError("ledger_change_notifications_unavailable")

    def prepare(self, _paths):
        pass

    def drain(self):
        from ctypes import wintypes
        changed = set()
        for _batch in range(64):
            transferred = wintypes.DWORD()
            if not self._api.GetOverlappedResult(self._handle, ctypes.byref(self._overlap),
                                               ctypes.byref(transferred), False):
                if ctypes.get_last_error() == 996:  # ERROR_IO_INCOMPLETE, no queued notices.
                    return changed
                raise RuntimeError("ledger_change_notifications_unavailable")
            raw = self._buffer.raw[:transferred.value]
            self._arm()
            if not raw:
                return None  # Overflow: the system discarded the notification batch.
            position = 0
            while True:
                following, _action, length = struct.unpack_from("III", raw, position)
                name = raw[position + 12:position + 12 + length].decode("utf-16-le")
                changed.add(self.root / name)
                if not following:
                    break
                position += following
        return None
