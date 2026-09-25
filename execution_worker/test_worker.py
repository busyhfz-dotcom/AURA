import os
import tempfile
import unittest

from main import WorkerStore


class ExecutionWorkerTests(unittest.TestCase):
    def test_worker_idempotency_replays_completed_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = WorkerStore(os.path.join(tmp, "worker.db"))
            first = store.reserve("worker-key-1234", "hash-a")
            self.assertTrue(first["is_new"])
            store.complete("worker-key-1234", {"status": "FILLED", "deal_id": 42})
            replay = store.reserve("worker-key-1234", "hash-a")
            self.assertFalse(replay["is_new"])
            self.assertEqual(replay["state"], "COMPLETED")
            self.assertEqual(replay["result"]["deal_id"], 42)

    def test_worker_rejects_same_key_for_different_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = WorkerStore(os.path.join(tmp, "worker.db"))
            store.reserve("worker-key-1234", "hash-a")
            with self.assertRaises(ValueError):
                store.reserve("worker-key-1234", "hash-b")


if __name__ == "__main__":
    unittest.main()
