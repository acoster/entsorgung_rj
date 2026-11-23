"""Unit tests for `entsorgung_rj.storage`."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from entsorgung_rj.storage import load_or_create_identity


class TestStorage(unittest.TestCase):
    def test_creates_and_reloads_cached_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "nested" / "client.json"

            first = load_or_create_identity(state)
            self.assertTrue(first.is_new)
            self.assertTrue(state.exists())

            saved = json.loads(state.read_text(encoding="utf-8"))
            self.assertEqual(saved["anonymous_user_id"], first.anonymous_user_id)
            self.assertEqual(saved["device_token"], first.device_token)

            second = load_or_create_identity(state)
            self.assertFalse(second.is_new)
            self.assertEqual(second.anonymous_user_id, first.anonymous_user_id)
            self.assertEqual(second.device_token, first.device_token)

    def test_user_id_override_bypasses_disk_and_marks_new(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "client.json"
            ident = load_or_create_identity(state, user_id_override="override-uid")
            self.assertTrue(ident.is_new)
            self.assertEqual(ident.anonymous_user_id, "override-uid")
            self.assertEqual(ident.device_token, "cli-override-uid")
            self.assertFalse(state.exists())

    def test_token_override_with_cached_identity_marks_new_when_changed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "client.json"
            first = load_or_create_identity(state)

            same_tok = load_or_create_identity(
                state,
                token_override=first.device_token,
            )
            self.assertFalse(same_tok.is_new)

            diff_tok = load_or_create_identity(state, token_override="custom-tok")
            self.assertTrue(diff_tok.is_new)
            self.assertEqual(diff_tok.anonymous_user_id, first.anonymous_user_id)
            self.assertEqual(diff_tok.device_token, "custom-tok")

    def test_corrupted_or_invalid_cache_regenerates_identity(self) -> None:
        bad_contents = [
            "not json",
            "[]",
            '{"anonymous_user_id": null, "device_token": null}',
            '{"anonymous_user_id": "  ", "device_token": "tok"}',
        ]
        for content in bad_contents:
            with tempfile.TemporaryDirectory() as tmp:
                state = Path(tmp) / "client.json"
                state.write_text(content, encoding="utf-8")

                ident = load_or_create_identity(state)
                self.assertTrue(ident.is_new)
                self.assertNotEqual(ident.anonymous_user_id, "None")
                self.assertTrue(ident.anonymous_user_id)
                self.assertTrue(ident.device_token)

    def test_unwritable_state_path_is_non_fatal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "client.json"
            with mock.patch.object(
                Path, "write_text", side_effect=OSError("read-only")
            ):
                ident = load_or_create_identity(state)
            self.assertTrue(ident.is_new)
            self.assertTrue(ident.anonymous_user_id)


if __name__ == "__main__":
    unittest.main()
