"""
Autonomous Visualization Engine using Plotly.
Automatically inspects DataFrame column dtypes and dimensionalities to render
interactive Line, Bar, Donut, Grouped Bar, and Scatter charts.
"""
import logging
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

logger = logging.getLogger("TextToSQL.Visualizer")


class AutonomousVisualizer:
    """Autonomous chart recommender and Plotly figure generator."""

    def __init__(self, theme: str = "plotly_white"):
        self.theme = theme

    def recommend_chart_type(self, df: pd.DataFrame) -> Tuple[str, Dict[str, Any]]:
        """
        Analyze columns and determine the optimal chart type and dimension mapping.
        Returns (chart_type, mapping_dict).
        """
        if df.empty or len(df.columns) < 1:
            return "none", {}

        # 1. Classify columns
        temporal_cols = []
        numeric_cols = []
        categorical_cols = []

        for col in df.columns:
            # Check if temporal
            if pd.api.types.is_datetime64_any_dtype(df[col]):
                temporal_cols.append(col)
            elif any(k in str(col).lower() for k in ["date", "month", "year", "time", "day"]):
                # Try parsing sample
                try:
                    pd.to_datetime(df[col].dropna().head(10))
                    temporal_cols.append(col)
                    continue
                except Exception:
                    pass

            # Check if numeric
            if pd.api.types.is_numeric_dtype(df[col]):
                numeric_cols.append(col)
            else:
                categorical_cols.append(col)

        # 2. Decision Tree for Optimal Chart Recommendation

        # Scenario A: Time-series Line Chart
        if temporal_cols and numeric_cols:
            return "line", {
                "x": temporal_cols[0],
                "y": numeric_cols[0],
                "color": categorical_cols[0] if categorical_cols else None
            }

        # Scenario B: Single row / KPI metric
        if len(df) == 1 and numeric_cols:
            return "metric", {"metrics": numeric_cols}

        # Scenario C: Categorical vs Numeric Metric
        if categorical_cols and numeric_cols:
            cat_col = categorical_cols[0]
            num_col = numeric_cols[0]
            unique_count = df[cat_col].nunique()

            # Donut chart for small breakdown (<= 5 slices)
            if 2 <= unique_count <= 5 and len(categorical_cols) == 1:
                return "donut", {"names": cat_col, "values": num_col}

            # Multi-categorical grouped bar
            if len(categorical_cols) >= 2:
                return "grouped_bar", {
                    "x": cat_col,
                    "y": num_col,
                    "color": categorical_cols[1]
                }

            # Standard bar chart
            return "bar", {"x": cat_col, "y": num_col}

        # Scenario D: Multi-numeric Scatter Plot
        if len(numeric_cols) >= 2:
            return "scatter", {
                "x": numeric_cols[0],
                "y": numeric_cols[1],
                "color": categorical_cols[0] if categorical_cols else None
            }

        # Scenario E: Single Categorical Distribution
        if categorical_cols and not numeric_cols:
            return "bar", {"x": categorical_cols[0], "y": None}

        return "table", {}

    def generate_chart(self, df: pd.DataFrame, force_type: Optional[str] = None) -> Optional[Any]:
        """
        Generate an interactive Plotly figure based on automatic recommendation
        or user-forced chart selection.
        """
        if df.empty or len(df) == 0:
            return None

        try:
            import plotly.express as px
            import plotly.graph_objects as go
        except ImportError:
            logger.warning("Plotly is not installed.")
            return None

        chart_type, mapping = self.recommend_chart_type(df)
        if force_type and force_type != "auto":
            chart_type = force_type

        try:
            if chart_type == "line":
                fig = px.line(
                    df,
                    x=mapping.get("x", df.columns[0]),
                    y=mapping.get("y", df.columns[1] if len(df.columns) > 1 else df.columns[0]),
                    color=mapping.get("color"),
                    markers=True,
                    template=self.theme,
                    title="Trend Over Time"
                )
                fig.update_layout(hovermode="x unified")
                return fig

            elif chart_type == "donut":
                fig = px.pie(
                    df,
                    names=mapping.get("names", df.columns[0]),
                    values=mapping.get("values", df.columns[1]),
                    hole=0.45,
                    template=self.theme,
                    title="Proportional Distribution"
                )
                fig.update_traces(textinfo="percent+label")
                return fig

            elif chart_type in ["bar", "grouped_bar"]:
                x_col = mapping.get("x", df.columns[0])
                y_col = mapping.get("y")

                if y_col:
                    fig = px.bar(
                        df,
                        x=x_col,
                        y=y_col,
                        color=mapping.get("color"),
                        barmode="group" if chart_type == "grouped_bar" else "relative",
                        text_auto=".2s",
                        template=self.theme,
                        title=f"{y_col} by {x_col}"
                    )
                else:
                    # Count frequency
                    counts = df[x_col].value_counts().reset_index()
                    counts.columns = [x_col, "Count"]
                    fig = px.bar(
                        counts,
                        x=x_col,
                        y="Count",
                        text_auto=True,
                        template=self.theme,
                        title=f"Frequency of {x_col}"
                    )
                fig.update_layout(xaxis_tickangle=-35)
                return fig

            elif chart_type == "scatter":
                fig = px.scatter(
                    df,
                    x=mapping.get("x", df.columns[0]),
                    y=mapping.get("y", df.columns[1]),
                    color=mapping.get("color"),
                    template=self.theme,
                    title="Correlation Analysis"
                )
                return fig

        except Exception as e:
            logger.warning(f"Plotly generation error: {e}")
            return None

        return None
