# SPDX-License-Identifier: GPL-3.0-or-later
"""Synthetic unknown-effect observation counterexamples, not execution proof."""
import copy
import unittest
from fault import valid_result


class UnknownEffectObservationTests(unittest.TestCase):
    def setUp(self):
        self.digest = "a" * 64
        self.observation = {"fault": "close_after_input", "connections": 1,
            "inputForwarded": True, "methods": {"Input.insertText": 1, "Page.captureScreenshot": 2},
            "sourceSha256": self.digest, "stoppedByTest": True}

    def test_one_real_forward_no_replay(self):
        self.assertTrue(valid_result(self.observation, self.digest))

    def test_missing_or_different_source_rejected(self):
        for value in (None, {}, {**self.observation, "sourceSha256": "b" * 64}):
            with self.subTest(value=value):
                self.assertFalse(valid_result(value, self.digest))

    def test_reconnect_or_replay_rejected(self):
        for field, value in (("connections", 2), ("inputForwarded", False), ("stoppedByTest", False)):
            with self.subTest(field=field):
                self.assertFalse(valid_result({**self.observation, field: value}, self.digest))
        for methods in ({"Input.insertText": 2}, {"Input.insertText": 1, "Input.dispatchKeyEvent": 1}, {}):
            with self.subTest(methods=methods):
                self.assertFalse(valid_result({**self.observation, "methods": methods}, self.digest))

    def test_bool_counts_and_negative_counts_rejected(self):
        for value in (True, 0, -1, "1"):
            with self.subTest(value=value):
                observation = copy.deepcopy(self.observation)
                observation["methods"]["Input.insertText"] = value
                self.assertFalse(valid_result(observation, self.digest))
        self.assertFalse(valid_result({**self.observation, "connections": True}, self.digest))
