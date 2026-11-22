import unittest

from simple_phone.core.endpoint import Endpoint


class FakeCall:
    def __init__(self, ref, call_id):
        self.ref, self.call_id, self.ended_at = ref, call_id, None

    def getId(self):  # noqa: N802 - PJSUA2 name
        return self.call_id


class ReapTest(unittest.TestCase):
    def test_drops_children_that_never_started(self):
        phone = Endpoint.__new__(Endpoint)  # no native library needed
        live, orphan = FakeCall("live", 3), FakeCall("orphan", -1)
        phone.calls = {"live": live, "orphan": orphan}
        phone.reap()
        self.assertEqual(phone.calls, {"live": live})


if __name__ == "__main__":
    unittest.main()
