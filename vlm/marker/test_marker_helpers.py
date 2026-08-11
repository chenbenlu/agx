import unittest

from detection_utils import canonicalize_class_id, target_matches
from marker_palette import ColorRegistry, stable_palette_index
from pose_utils import quaternion_to_yaw


class MarkerHelperTest(unittest.TestCase):
    def test_canonicalize_class_id_normalizes_articles_and_separators(self) -> None:
        self.assertEqual(canonicalize_class_id("A black_bicycle."), "black bicycle")

    def test_target_filter_allows_empty_filter(self) -> None:
        self.assertTrue(target_matches("black bicycle", ""))

    def test_target_filter_matches_prompt_like_text(self) -> None:
        self.assertTrue(target_matches("black bicycle", "person. black bicycle."))
        self.assertFalse(target_matches("chair", "person. black bicycle."))

    def test_stable_palette_index_is_repeatable(self) -> None:
        self.assertEqual(
            stable_palette_index("black bicycle"),
            stable_palette_index("Black-Bicycle"),
        )

    def test_color_registry_reuses_same_color_for_same_class(self) -> None:
        registry = ColorRegistry()
        self.assertEqual(
            registry.color_for("black bicycle"),
            registry.color_for("Black-Bicycle"),
        )

    def test_color_registry_uses_different_colors_for_common_classes(self) -> None:
        registry = ColorRegistry()
        self.assertNotEqual(registry.color_for("black bicycle"), registry.color_for("person"))

    def test_quaternion_to_yaw_zero(self) -> None:
        self.assertAlmostEqual(quaternion_to_yaw(0.0, 0.0, 0.0, 1.0), 0.0)


if __name__ == "__main__":
    unittest.main()
