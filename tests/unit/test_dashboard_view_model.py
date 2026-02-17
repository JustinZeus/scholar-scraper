from __future__ import annotations

from datetime import datetime, timezone

from app.db.models import CrawlRun, RunStatus, RunTriggerType
from app.presentation.dashboard import SECTION_TEMPLATES, build_dashboard_view_model
from app.services.publications import UnreadPublicationItem


def test_build_dashboard_view_model_maps_sections_and_unread_items() -> None:
    unread_items = [
        UnreadPublicationItem(
            publication_id=10,
            scholar_profile_id=3,
            scholar_label="Ada Lovelace",
            title="Analytical Engine Notes",
            year=None,
            citation_count=42,
            venue_text="Computing Letters",
            pub_url="https://example.test/pub-10",
        )
    ]
    runs = [
        CrawlRun(
            id=77,
            user_id=1,
            trigger_type=RunTriggerType.MANUAL,
            status=RunStatus.SUCCESS,
            start_dt=datetime(2026, 2, 16, 18, 0, tzinfo=timezone.utc),
            scholar_count=1,
            new_pub_count=1,
            error_log={},
        )
    ]

    vm = build_dashboard_view_model(
        unread_publications=unread_items,
        recent_runs=runs,
        request_delay_seconds=7,
        queue_counts={"queued": 2, "retrying": 1, "dropped": 3},
    )

    assert vm.section_templates == SECTION_TEMPLATES
    assert vm.run_controls.request_delay_seconds == 7
    assert vm.run_controls.queue_queued_count == 2
    assert vm.run_controls.queue_retrying_count == 1
    assert vm.run_controls.queue_dropped_count == 3
    assert vm.unread_publications[0].title == "Analytical Engine Notes"
    assert vm.unread_publications[0].year_display == "-"
    assert vm.unread_publications[0].citation_count == 42
    assert vm.run_history[0].status_label == "success"
    assert vm.run_history[0].status_badge == "ok"
    assert vm.run_history[0].started_at_display == "2026-02-16 18:00 UTC"
    assert vm.run_history[0].detail_url == "/runs/77"


def test_build_dashboard_view_model_maps_failed_and_partial_statuses() -> None:
    runs = [
        CrawlRun(
            id=11,
            user_id=1,
            trigger_type=RunTriggerType.MANUAL,
            status=RunStatus.FAILED,
            start_dt=datetime(2026, 2, 16, 19, 0, tzinfo=timezone.utc),
            scholar_count=2,
            new_pub_count=0,
            error_log={},
        ),
        CrawlRun(
            id=12,
            user_id=1,
            trigger_type=RunTriggerType.MANUAL,
            status=RunStatus.PARTIAL_FAILURE,
            start_dt=datetime(2026, 2, 16, 20, 0, tzinfo=timezone.utc),
            scholar_count=2,
            new_pub_count=1,
            error_log={},
        ),
    ]

    vm = build_dashboard_view_model(
        unread_publications=[],
        recent_runs=runs,
        request_delay_seconds=1,
    )

    assert [item.status_badge for item in vm.run_history] == ["danger", "warn"]
    assert [item.status_label for item in vm.run_history] == ["failed", "partial_failure"]
