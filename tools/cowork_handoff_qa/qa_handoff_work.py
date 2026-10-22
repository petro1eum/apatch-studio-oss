"""Fixed, non-LLM QA work process. Emits liveness until the container is stopped."""
import json
import os
import subprocess
import sys
import time


def main():
    if sys.platform != 'linux' or os.getuid() != 1000:
        raise RuntimeError('This work runs only in the admitted unprivileged Linux container')
    prompt = sys.stdin.buffer.read(65537)
    if len(prompt) > 65536:
        raise RuntimeError('Native input exceeds the fixed QA limit')
    # A separate session deliberately defeats process-group-only stop approaches.
    child = subprocess.Popen([sys.executable, '-I', '-B', '-c',
        'import time\nwhile True: time.sleep(1)'], start_new_session=True,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        env={'PATH': '/usr/local/bin:/usr/bin:/bin'}, cwd='/workspace')
    try:
        while True:
            if child.poll() is not None:
                raise RuntimeError('The expected QA descendant exited')
            print(json.dumps({'type': 'qa.heartbeat', 'pid': os.getpid(), 'child_pid': child.pid}), flush=True)
            time.sleep(1)
    finally:
        child.terminate()
        child.wait(timeout=5)


if __name__ == '__main__':
    main()
