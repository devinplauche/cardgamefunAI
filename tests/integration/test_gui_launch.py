import unittest
import sys
import subprocess
import os
import time


class TestGUILaunch(unittest.TestCase):
    def test_basic_py_gui_launches(self):
        """Launch the Tkinter GUI in a subprocess, confirm it starts, then terminate."""
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
        script_path = os.path.join(repo_root, 'src', 'simple-start', 'basic.py')

        # Use the same Python interpreter running the tests
        proc = subprocess.Popen([sys.executable, script_path])
        try:
            # Give the GUI a moment to start
            time.sleep(1.0)
            # Check process is still running
            self.assertIsNone(proc.poll(), "GUI process exited unexpectedly")
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except Exception:
                proc.kill()


if __name__ == '__main__':
    unittest.main()
