"""Settings file: validation, atomic save, never crashing on bad files."""
import json
import os
import tempfile
import types
import unittest

from screenshare import config, settings


class Validate(unittest.TestCase):
    def test_defaults_when_empty(self):
        clean, errors = settings.validate({})
        self.assertEqual(clean, settings.DEFAULTS)
        self.assertEqual(errors, {})

    def test_defaults_match_config(self):
        d = settings.DEFAULTS
        self.assertEqual((d["port"], d["fps"], d["jpeg_quality"], d["max_width"],
                          d["max_height"], d["max_viewers"]),
                         (config.PORT, config.TARGET_FPS, config.JPEG_QUALITY,
                          config.MAX_SCREEN_WIDTH, config.MAX_SCREEN_HEIGHT, config.MAX_VIEWERS))
        self.assertEqual(settings.TEXT_MAX["viewer_name"], config.CLIENT_NAME_MAX_LENGTH)

    def test_strings_from_the_dialog_are_accepted(self):
        clean, errors = settings.validate({"port": " 5100 ", "fps": "10"})
        self.assertEqual((clean["port"], clean["fps"], errors), (5100, 10, {}))

    def test_bad_values_report_and_fall_back(self):
        bad = {"port": 80, "fps": "fast", "jpeg_quality": True, "max_viewers": 3,
               "viewer_name": "x" * 33, "last_host": 5}
        clean, errors = settings.validate(bad)
        self.assertEqual(set(errors), set(bad))
        for key in bad:
            self.assertEqual(clean[key], settings.DEFAULTS[key], key)

    def test_limits_are_inclusive(self):
        for key, (low, high) in settings.LIMITS.items():
            for value in (low, high):
                self.assertEqual(settings.validate({key: value})[1], {}, (key, value))
            for value in (low - 1, high + 1):
                self.assertIn(key, settings.validate({key: value})[1], (key, value))

    def test_non_dict_input(self):
        self.assertEqual(settings.validate("junk")[0], settings.DEFAULTS)


class Persistence(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.dir.name, "sub", "settings.json")

    def tearDown(self):
        self.dir.cleanup()

    def test_round_trip_and_folder_creation(self):
        saved = settings.save({"port": 5200, "fps": 8, "viewer_name": "Laptop B"}, self.path)
        self.assertEqual(settings.load(self.path), saved)
        self.assertEqual(saved["port"], 5200)
        self.assertEqual(os.listdir(os.path.dirname(self.path)), ["settings.json"])

    def test_save_refuses_bad_values_and_keeps_old_file(self):
        settings.save({"port": 5200}, self.path)
        with self.assertRaises(ValueError):
            settings.save({"port": 99999}, self.path)
        self.assertEqual(settings.load(self.path)["port"], 5200)

    def test_corrupt_missing_and_wrong_shape_files_give_defaults(self):
        self.assertEqual(settings.load(self.path), settings.DEFAULTS)         # missing
        os.makedirs(os.path.dirname(self.path))
        for content in ("{not json", "[1, 2]", "", '{"port": "abc", "fps": 6}'):
            with open(self.path, "w", encoding="utf-8") as f:
                f.write(content)
            loaded = settings.load(self.path)
            self.assertEqual(loaded["port"], 5000, content)
        self.assertEqual(loaded["fps"], 6)

    def test_env_override_for_path(self):
        os.environ["SCREENSHARE_SETTINGS"] = self.path
        try:
            self.assertEqual(settings.settings_path(), self.path)
        finally:
            del os.environ["SCREENSHARE_SETTINGS"]


class Apply(unittest.TestCase):
    def fake_cfg(self):
        return types.SimpleNamespace(DEMO_SLOW_VIEWER_MS=250)

    def test_apply_sets_config_values(self):
        cfg = self.fake_cfg()
        settings.apply({"port": 5300, "fps": 9, "jpeg_quality": 50, "max_width": 800,
                        "max_height": 600, "max_viewers": 1, "slow_viewer_ms": 400}, cfg)
        self.assertEqual((cfg.PORT, cfg.TARGET_FPS, cfg.JPEG_QUALITY, cfg.MAX_SCREEN_WIDTH,
                          cfg.MAX_SCREEN_HEIGHT, cfg.MAX_VIEWERS, cfg.DEMO_SLOW_VIEWER_MS),
                         (5300, 9, 50, 800, 600, 1, 400))

    def test_zero_slow_viewer_keeps_the_environment_value(self):
        cfg = self.fake_cfg()
        settings.apply({"slow_viewer_ms": 0}, cfg)
        self.assertEqual(cfg.DEMO_SLOW_VIEWER_MS, 250)

    def test_apply_rejects_bad_values_without_touching_config(self):
        cfg = self.fake_cfg()
        with self.assertRaises(ValueError):
            settings.apply({"port": 1}, cfg)
        self.assertFalse(hasattr(cfg, "PORT"))


if __name__ == "__main__":
    unittest.main()
