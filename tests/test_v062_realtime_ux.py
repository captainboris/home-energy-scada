import unittest
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
FRONTEND = PROJECT / "source" / "frontend-react"


class RealtimeUxSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.overview = (FRONTEND / "src" / "overview.tsx").read_text()
        cls.cards = (FRONTEND / "src" / "components" / "CurrentReadings.tsx").read_text()
        cls.chart = (FRONTEND / "src" / "components" / "HistorianChart.tsx").read_text()
        cls.css = (FRONTEND / "public" / "shared.css").read_text()
        cls.config = (FRONTEND / "src" / "config.ts").read_text()

    def test_current_readings_are_period_independent(self):
        self.assertIn("shouldPollCurrentReadings(document.hidden)", self.overview)
        self.assertIn("periodRef.current", self.overview)
        self.assertNotIn("liveCursor.current = null", self.overview)
        self.assertNotIn("setCurrentLatest(previous => mergeLatest(previous, body.data.latest", self.overview.split("useEffect(() => { loadHistory")[0])

    def test_four_dense_energy_flow_cards_and_capacity(self):
        for token in ("flow.pv", "flow.homeLoad", "flow.battery", "flow.grid",
                      "battery_charge_power_kw", "battery_discharge_power_kw",
                      "grid_import_power_kw", "grid_export_power_kw", "≈"):
            self.assertIn(token, self.cards)
        self.assertIn("VITE_BATTERY_CAPACITY_KWH", self.config)
        self.assertEqual(self.config.count("\n  28\n"), 1)

    def test_drag_selection_has_overlay_only_and_suppresses_tooltip(self):
        self.assertIn('className="zoom-selection" hidden', self.chart)
        self.assertNotIn("selectionLabel", self.chart)
        self.assertNotIn('t("chart.zooming"', self.chart)
        self.assertIn(".echart.is-selecting .historian-tooltip{display:none!important}", self.css)
        self.assertIn("touch-action:pan-y", self.css)
        self.assertNotIn("touch-action:pan-y pinch-zoom", self.css)

    def test_product_governance_documents_exist(self):
        for relative in (
            "docs/PRODUCT_SPEC.md",
            "docs/UI_BEHAVIOUR_SPEC.md",
            "docs/DATA_SEMANTICS.md",
            "docs/REGRESSION_CHECKLIST.md",
        ):
            self.assertTrue((PROJECT / relative).is_file(), relative)


if __name__ == "__main__":
    unittest.main()
