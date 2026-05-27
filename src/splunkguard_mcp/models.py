"""Structured result types returned by `SplunkInvestigator`."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RecommendedAction:
    """A single recommended next step, optionally with a paste-ready SPL query."""

    action: str
    spl_query: str = ""
    confidence: str = "medium"  # low | medium | high


@dataclass
class SplunkInvestigationReport:
    """Structured report returned by `SplunkInvestigator.investigate(question)`."""

    question: str
    root_cause: str
    investigation_category: str = "unknown"
    # known categories: anomaly | threshold_breach | pipeline_failure |
    # security_event | performance_degradation | data_gap | unknown
    affected_components: list[str] = field(default_factory=list)
    time_range: str = ""
    is_ongoing: bool = False
    recommended_actions: list[RecommendedAction] = field(default_factory=list)
    full_analysis: str = ""
