import unittest
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
FRONTEND = PROJECT / "source" / "frontend-react"


class HistorianInteractionSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chart = (FRONTEND / "src" / "components" / "HistorianChart.tsx").read_text()
        cls.overview = (FRONTEND / "src" / "overview.tsx").read_text()
        cls.zoom = (FRONTEND / "src" / "zoom.ts").read_text()

    def test_axis_uses_selected_period_not_now(self):
        self.assertIn("selectedPeriodRange(period, history?.range)", self.overview)
        self.assertNotIn("Math.min(history.range.end_ms, now)", self.overview)
        self.assertIn("min: fullRange.from", self.chart)
        self.assertIn("max: fullRange.to", self.chart)

    def test_native_pan_and_pinch_are_disabled(self):
        self.assertIn("disabled: true", self.chart)
        self.assertIn("zoomOnMouseWheel: false", self.chart)
        self.assertIn("moveOnMouseMove: false", self.chart)
        self.assertIn("moveOnMouseWheel: false", self.chart)
        self.assertIn("dragZoomRange", self.chart)
        self.assertIn("zoomAroundAnchor", self.chart)

    def test_only_x_axis_has_data_zoom(self):
        self.assertIn("xAxisIndex: 0", self.chart)
        self.assertNotIn("yAxisIndex", self.chart)

    def test_toolbar_and_tooltip_state_are_explicit(self):
        self.assertIn("lastSyncedZoom", self.chart)
        self.assertIn("toolbar.showSync", self.chart)
        self.assertIn("toolbar.showRestore", self.chart)
        self.assertIn("tooltipContains", self.chart)
        self.assertIn('type: "hideTip"', self.chart)
        self.assertIn("zoomToolbarState", self.zoom)


if __name__ == "__main__":
    unittest.main()
