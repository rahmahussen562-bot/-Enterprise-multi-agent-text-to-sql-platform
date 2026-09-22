"""
Tests for utils.visualizer AutonomousVisualizer.
"""
import unittest
import pandas as pd
from utils.visualizer import AutonomousVisualizer


class TestAutonomousVisualizer(unittest.TestCase):
    def setUp(self):
        self.visualizer = AutonomousVisualizer()

    def test_recommend_time_series_line(self):
        df = pd.DataFrame({
            "OrderDate": pd.date_range("2024-01-01", periods=5),
            "Revenue": [100.5, 220.0, 180.0, 310.2, 450.0]
        })
        chart_type, mapping = self.visualizer.recommend_chart_type(df)
        self.assertEqual(chart_type, "line")
        self.assertEqual(mapping["x"], "OrderDate")
        self.assertEqual(mapping["y"], "Revenue")

        fig = self.visualizer.generate_chart(df)
        self.assertIsNotNone(fig)

    def test_recommend_categorical_bar(self):
        df = pd.DataFrame({
            "Country": ["Brazil", "USA", "Germany", "Canada", "France", "Japan", "UK", "Italy"],
            "TotalSales": [450, 1200, 300, 550, 280, 700, 950, 420]
        })
        chart_type, mapping = self.visualizer.recommend_chart_type(df)
        self.assertEqual(chart_type, "bar")

        fig = self.visualizer.generate_chart(df)
        self.assertIsNotNone(fig)

    def test_recommend_donut_chart(self):
        df = pd.DataFrame({
            "Genre": ["Rock", "Jazz", "Metal"],
            "Tracks": [45, 12, 28]
        })
        chart_type, mapping = self.visualizer.recommend_chart_type(df)
        self.assertEqual(chart_type, "donut")

        fig = self.visualizer.generate_chart(df)
        self.assertIsNotNone(fig)


if __name__ == "__main__":
    unittest.main()
