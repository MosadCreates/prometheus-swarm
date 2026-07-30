"""Progress bar components for live streaming UI."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from rich.text import Text

from prometheus.ui.theme import Theme


# Unicode block characters
FULL_BLOCK = "█"
EMPTY_BLOCK = "░"
HALF_BLOCK = "▌"

BAR_COLORS = {
    "default": str(Theme.success),
    "confidence": str(Theme.info),
    "training": str(Theme.warning),
    "dataset": str(Theme.info),
    "error": str(Theme.error),
}

BAR_EMPTY = str(Theme.muted)
BAR_LABEL = str(Theme.muted)
BAR_DETAIL = str(Theme.muted)
BAR_PERCENT = str(Theme.body)


@dataclass
class ProgressBar:
    """A progress bar with label, percentage, and optional detail.

    Variants:
    - Confidence: [█████████░] 91%
    - Training:   [████████████████░░░░░░░░] 52% │ Fold 3/5 │ Loss: 0.231
    - Dataset:    [███████░░░░] 67% (891 rows)
    """

    value: float = 0.0  # 0.0 to 1.0
    label: str = ""
    detail: str = ""
    width: int = 40
    show_percentage: bool = True
    style: str = "default"  # default, confidence, training, dataset, error

    def set_value(self, value: float) -> None:
        self.value = max(0.0, min(1.0, value))

    def _color_for_style(self) -> str:
        return BAR_COLORS.get(self.style, str(Theme.success))

    def render(self) -> Text:
        """Render the progress bar as Rich Text."""
        filled = int(self.width * self.value)
        empty = self.width - filled

        fill_color = self._color_for_style()

        line = Text()

        if self.label:
            line.append(f"{self.label:<14} ", style=BAR_LABEL)

        # Bar
        line.append("[", style="dim")
        line.append(FULL_BLOCK * filled, style=fill_color)
        line.append(EMPTY_BLOCK * empty, style=BAR_EMPTY)
        line.append("]", style="dim")

        if self.show_percentage:
            pct = int(self.value * 100)
            line.append(f" {pct:3d}%", style=BAR_PERCENT)

        if self.detail:
            line.append(f" │ {self.detail}", style=BAR_DETAIL)

        return line

    def render_inline(self, indent: str = "   \u2502   \u23bf ") -> Text:
        filled = int(self.width * self.value)
        empty = self.width - filled
        fill_color = self._color_for_style()

        t = Text()
        t.append(indent, style=str(Theme.muted))
        t.append("[", style="dim")
        t.append(FULL_BLOCK * filled, style=fill_color)
        t.append(EMPTY_BLOCK * empty, style=BAR_EMPTY)
        t.append("]", style="dim")
        if self.show_percentage:
            pct = int(self.value * 100)
            t.append(f" {pct:3d}%", style=BAR_PERCENT)
        if self.detail:
            t.append(f" \u00b7 {self.detail}", style=BAR_DETAIL)
        return t

    def __str__(self) -> str:
        return str(self.render())


@dataclass
class MultiProgressBar:
    """Multiple progress bars stacked vertically."""

    bars: list[ProgressBar] = field(default_factory=list)

    def add_bar(self, bar: ProgressBar) -> None:
        self.bars.append(bar)

    def render(self) -> Text:
        result = Text()
        for i, bar in enumerate(self.bars):
            if i > 0:
                result.append("\n")
            result.append_text(bar.render())
        return result


def create_confidence_bar(confidence: float, label: str = "Confidence") -> ProgressBar:
    """Create a confidence progress bar."""
    return ProgressBar(
        value=confidence,
        label=label,
        width=30,
        style="confidence",
    )


def create_training_bar(
    progress: float,
    fold: int | None = None,
    total_folds: int | None = None,
    loss: float | None = None,
    metric_name: str | None = None,
    metric_value: float | None = None,
    label: str = "Training",
) -> ProgressBar:
    """Create a training progress bar with fold/loss info."""
    detail_parts = []
    if fold is not None and total_folds is not None:
        detail_parts.append(f"Fold {fold}/{total_folds}")
    if loss is not None:
        detail_parts.append(f"Loss: {loss:.3f}")
    if metric_name and metric_value is not None:
        detail_parts.append(f"{metric_name}: {metric_value:.4f}")

    return ProgressBar(
        value=progress,
        label=label,
        detail=" │ ".join(detail_parts),
        width=40,
        style="training",
    )


def create_dataset_bar(
    rows_processed: int,
    total_rows: int,
    label: str = "Dataset",
) -> ProgressBar:
    """Create a dataset processing progress bar."""
    progress = rows_processed / max(total_rows, 1)
    return ProgressBar(
        value=progress,
        label=label,
        detail=f"({total_rows:,} rows)",
        width=30,
        style="dataset",
    )


def create_fold_bar(
    fold: int,
    total_folds: int,
    fold_progress: float,
    metric_name: str = "AUC",
    metric_value: float = 0.0,
) -> ProgressBar:
    """Create a fold-specific progress bar."""
    return ProgressBar(
        value=fold_progress,
        label=f"Fold {fold}/{total_folds}",
        detail=f"{metric_name}: {metric_value:.4f}",
        width=35,
        style="training",
    )
