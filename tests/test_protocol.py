# file: tests/test_protocol.py
"""JSON message contract: required fields, types, directions and the exact reason
lists (architecture sections 5.5, 5.7 and 5.8). Pure logic, no sockets."""
import unittest

import screenshare.protocol as P

V2H = P.VIEWER_TO_HOST
H2V = P.HOST_TO_VIEWER


class ReasonLists(unittest.TestCase):
    def test_exact_reason_lists(self):
        self.assertEqual(P.JOIN_DENIED_REASONS, frozenset({
            "invalid_session_code", "viewer_limit_reached", "unsupported_version", "invalid_name"}))
        self.assertEqual(P.CONTROL_DENIED_REASONS, frozenset({
            "controller_busy", "request_pending", "host_rejected"}))
        self.assertEqual(P.CONTROL_REVOKED_REASONS, frozenset({
            "host_revoked", "failsafe", "host_stopped"}))
        self.assertEqual(P.DISCONNECT_REASONS, frozenset({"host_stopped", "user_exit"}))
        self.assertEqual(P.ERROR_REASONS, frozenset({"unsupported_message", "invalid_input"}))


class Directions(unittest.TestCase):
    def test_viewer_messages_accepted_only_viewer_to_host(self):
        for mtype in P.VIEWER_TO_HOST_TYPES - {"DISCONNECT"}:
            msg = {"type": mtype}
            msg.update(self._fields(mtype))
            self.assertIsNone(P.validate_message(msg, V2H), mtype)
            self.assertEqual(P.validate_message(msg, H2V), "unsupported_message", mtype)

    def test_host_messages_accepted_only_host_to_viewer(self):
        for mtype in P.HOST_TO_VIEWER_TYPES - {"DISCONNECT"}:
            msg = {"type": mtype}
            msg.update(self._fields(mtype))
            self.assertIsNone(P.validate_message(msg, H2V), mtype)
            self.assertEqual(P.validate_message(msg, V2H), "unsupported_message", mtype)

    def test_disconnect_is_allowed_in_both_directions(self):
        for direction in (V2H, H2V):
            self.assertIsNone(P.validate_message({"type": "DISCONNECT"}, direction))

    def test_unknown_type_rejected_both_ways(self):
        for direction in (V2H, H2V):
            self.assertEqual(P.validate_message({"type": "SHELL"}, direction),
                             "unsupported_message")
            self.assertEqual(P.validate_message({}, direction), "unsupported_message")

    @staticmethod
    def _fields(mtype):
        sample = {
            "protocol_version": 1, "client_name": "Laptop B", "session_code": "ABCD2345",
            "viewer_id": "abc", "host_name": "Laptop A", "screen_width": 1280,
            "screen_height": 720, "fps": 5, "reason": "host_revoked",
            "viewer_count": 2, "active_controller": None, "pending_requester": None,
            "x": 0.5, "y": 0.5, "button": "left", "action": "down", "amount": 1,
            "key": "enter", "id": 7,
        }
        return {name: sample[name] for name, _types in P.REQUIRED_FIELDS.get(mtype, ())}


class RequiredFields(unittest.TestCase):
    def test_join_requires_three_fields_with_right_types(self):
        good = {"type": "JOIN", "protocol_version": 1,
                "client_name": "Laptop B", "session_code": "ABCD2345"}
        self.assertIsNone(P.validate_message(good, V2H))
        for field in ("protocol_version", "client_name", "session_code"):
            missing = dict(good)
            del missing[field]
            self.assertEqual(P.validate_message(missing, V2H), "unsupported_message", field)
        for field, bad in (("protocol_version", "1"), ("protocol_version", True),
                           ("client_name", 7), ("session_code", None)):
            wrong = dict(good, **{field: bad})
            self.assertEqual(P.validate_message(wrong, V2H), "unsupported_message", field)

    def test_extra_unknown_fields_are_ignored(self):
        msg = {"type": "CONTROL_REQUEST", "viewer_id": "spoofed", "extra": [1, 2]}
        self.assertIsNone(P.validate_message(msg, V2H))

    def test_status_allows_null_controller_fields(self):
        base = {"type": "STATUS", "viewer_count": 2}
        self.assertIsNone(P.validate_message(
            dict(base, active_controller=None, pending_requester=None), H2V))
        self.assertIsNone(P.validate_message(
            dict(base, active_controller="Laptop B", pending_requester="Laptop C"), H2V))
        self.assertEqual(P.validate_message(
            dict(base, active_controller=3, pending_requester=None), H2V), "unsupported_message")
        self.assertEqual(P.validate_message(base, H2V), "unsupported_message")

    def test_input_fields_are_numeric_not_boolean_or_text(self):
        move = {"type": "MOUSE_MOVE", "x": 0.5, "y": 0.5}
        self.assertIsNone(P.validate_message(move, V2H))
        for bad in (True, "0.5", None):
            self.assertEqual(P.validate_message(dict(move, x=bad), V2H), "unsupported_message")
        # Range is the input handler's job, not the field check's.
        self.assertIsNone(P.validate_message(dict(move, x=9.0), V2H))

    def test_scroll_amount_must_be_an_integer(self):
        scroll = {"type": "SCROLL", "amount": 2, "x": 0.5, "y": 0.5}
        self.assertIsNone(P.validate_message(scroll, V2H))
        for bad in (2.5, True, "2", None):
            self.assertEqual(P.validate_message(dict(scroll, amount=bad), V2H),
                             "unsupported_message")

    def test_button_and_key_fields_required(self):
        self.assertEqual(P.validate_message(
            {"type": "MOUSE_BUTTON", "button": "left", "x": 0.5, "y": 0.5}, V2H),
            "unsupported_message")
        self.assertEqual(P.validate_message({"type": "KEY_DOWN"}, V2H), "unsupported_message")
        self.assertIsNone(P.validate_message({"type": "KEY_UP", "key": "a"}, V2H))

    def test_disconnect_reason_is_optional(self):
        self.assertIsNone(P.validate_message({"type": "DISCONNECT"}, V2H))
        self.assertIsNone(P.validate_message({"type": "DISCONNECT", "reason": "user_exit"}, H2V))


if __name__ == "__main__":
    unittest.main()
