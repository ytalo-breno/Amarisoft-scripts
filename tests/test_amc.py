import unittest
from unittest.mock import Mock, patch

from AMCBasedMitigation import APIError, Controller, RemoteAPI


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.api = Mock()
        self.controller = Controller(self.api)

    def poll(self, *samples):
        self.api.request.return_value = {"ue_list": [{"cells": list(samples)}]}
        self.controller.poll()

    def sample(self, **overrides):
        return dict(dict(cell_id=1, cqi=15, dl_mcs=10, dl_bler=0.2), **overrides)

    def test_missing_bler_never_changes_mcs(self):
        sample = self.sample()
        del sample["dl_bler"]
        self.poll(sample)
        self.api.request.assert_called_once_with("ue_get", stats=True)

    def test_high_bler_at_zero_does_not_raise_mcs(self):
        self.poll(self.sample(dl_mcs=0))
        self.api.request.assert_called_once_with("ue_get", stats=True)

    def test_one_command_per_cell_respects_worst_cqi(self):
        self.poll(self.sample(), self.sample(cqi=3))
        self.api.request.assert_called_with("config_set", cells={"1": {"pdsch_mcs": 2}})
        self.assertEqual(self.api.request.call_count, 2)

    def test_recovery_requires_three_good_samples(self):
        for _ in range(2):
            self.poll(self.sample(dl_bler=0.01))
        self.assertEqual(self.api.request.call_count, 2)
        self.poll(self.sample(dl_bler=0.01))
        self.api.request.assert_called_with("config_set", cells={"1": {"pdsch_mcs": 11}})

    def test_disconnection_clears_recovery(self):
        self.poll(self.sample(dl_bler=0.01))
        self.poll()
        self.assertEqual(self.controller.stable, {})

    def test_command_error_propagates(self):
        self.api.request.side_effect = [
            {"ue_list": [{"cells": [self.sample()]}]}, APIError("rejected")]
        with self.assertRaises(APIError):
            self.controller.poll()


class ProtocolTests(unittest.TestCase):
    @patch("AMCBasedMitigation.websocket.create_connection")
    def test_ready_events_and_response_correlation(self, connect):
        ws = connect.return_value
        ws.recv.side_effect = [
            '{"message":"ready","type":"ENB"}',
            '{"message":"event"}',
            '{"message":"ue_get","message_id":999}',
            '{"message":"ue_get","message_id":1,"ue_list":[]}']
        api = RemoteAPI("ws://example")
        self.assertEqual(api.request("ue_get", stats=True)["ue_list"], [])
        api.close()
        ws.close.assert_called_once()

    @patch("AMCBasedMitigation.websocket.create_connection")
    def test_authentication_requirement_is_explicit(self, connect):
        connect.return_value.recv.return_value = '{"message":"authenticate"}'
        with self.assertRaises(APIError):
            RemoteAPI("ws://example")
        connect.return_value.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
