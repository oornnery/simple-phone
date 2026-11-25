import unittest

from simple_phone.core.sip import SipMessage, dialog_state

COMPACT_NOTIFY = (
    "NOTIFY sip:1001@10.0.0.2:5070 SIP/2.0\r\n"
    "v: SIP/2.0/UDP 10.0.0.1:5060;branch=z9hG4bK1\r\n"
    "f: <sip:1002@pbx>;tag=a\r\n"
    "t: <sip:1001@pbx>;tag=b\r\n"
    "i: abc@pbx\r\n"
    "CSeq: 2 NOTIFY\r\n"
    "o: dialog\r\n"
    "c: application/dialog-info+xml\r\n"
    "l: 0\r\n"
    "\r\n"
    '<dialog-info entity="sip:1002@pbx"><dialog id="1">'
    "<state>confirmed</state></dialog></dialog-info>"
)


class CompactHeadersTest(unittest.TestCase):
    def test_compact_names_read_as_full_names(self):
        msg = SipMessage(direction="RX", transport="UDP", peer="10.0.0.1:5060",
                         raw=COMPACT_NOTIFY)  # fmt: skip
        self.assertEqual(msg.call_id, "abc@pbx")
        self.assertEqual(msg.headers["event"], "dialog")
        self.assertEqual(msg.headers["content-type"], "application/dialog-info+xml")
        self.assertEqual(msg.cseq_method, "NOTIFY")
        self.assertEqual(dialog_state(msg)[:2], ("sip:1002@pbx", "confirmed"))


if __name__ == "__main__":
    unittest.main()
