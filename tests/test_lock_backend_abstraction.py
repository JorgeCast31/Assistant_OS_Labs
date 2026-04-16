import unittest


class TestLockBackendAbstraction(unittest.TestCase):
    def setUp(self):
        from assistant_os.control_plane.locks import reset_lock_backend

        reset_lock_backend()

    def test_local_process_backend_acquire_release_and_cleanup(self):
        from assistant_os.control_plane.lock_backend import LocalProcessLockBackend

        backend = LocalProcessLockBackend()
        lease = backend.acquire("restriction:test", timeout_seconds=0.0)
        self.assertTrue(lease.acquired)
        self.assertEqual(backend.active_lock_ids(), ["restriction:test"])
        second = backend.acquire("restriction:test", timeout_seconds=0.0)
        self.assertFalse(second.acquired)
        backend.release("restriction:test")
        self.assertEqual(backend.active_lock_ids(), [])
        self.assertEqual(backend.cleanup_unused(), 1)

    def test_file_backend_is_swappable_for_global_lock_manager(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory

        from assistant_os.control_plane.lock_backend import FileLockBackend
        from assistant_os.control_plane.locks import configure_lock_backend, lock_manager, reset_lock_backend

        with TemporaryDirectory() as tmp:
            configure_lock_backend(FileLockBackend(Path(tmp)))
            try:
                lease = lock_manager.acquire("restriction:test", owner_id="request-1", timeout_seconds=0.0)
                self.assertEqual(lock_manager.backend_name(), "FileLockBackend")
                self.assertEqual(lease.owner_id, "request-1")
                self.assertEqual(lock_manager.active_locks()[0]["lock_id"], "restriction:test")
                self.assertEqual(lock_manager.cleanup_unused_locks(), 0)
                lock_manager.release("restriction:test", owner_id="request-1")
                self.assertEqual(lock_manager.cleanup_unused_locks(), 0)
            finally:
                reset_lock_backend()


if __name__ == "__main__":
    unittest.main()
