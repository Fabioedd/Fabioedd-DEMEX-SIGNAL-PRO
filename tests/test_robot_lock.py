import tempfile
import unittest
from pathlib import Path

from robot_lock import acquire_robot_lock


class RobotInstanceLockTests(unittest.TestCase):
    def test_only_one_open_handle_can_own_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            lock_path = Path(directory) / ".demex-robot.lock"
            first = acquire_robot_lock(lock_path)
            self.assertIsNotNone(first)
            try:
                second = acquire_robot_lock(lock_path)
                self.assertIsNone(second)
            finally:
                first.close()

            third = acquire_robot_lock(lock_path)
            self.assertIsNotNone(third)
            third.close()


if __name__ == "__main__":
    unittest.main()
