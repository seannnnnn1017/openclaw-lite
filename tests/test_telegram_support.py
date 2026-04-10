from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.app.telegram_support import format_telegram_memory_event


def test_format_telegram_memory_event_hides_topics_messages():
    event = {
        "category": "memory",
        "text": "topics [notification-workflow.md]",
        "rendered": "  * memory    topics [notification-workflow.md]",
    }

    assert format_telegram_memory_event(event) == ""


def test_format_telegram_memory_event_keeps_other_memory_messages():
    event = {
        "category": "memory",
        "text": "wrote notification-workflow.md",
        "rendered": "  * memory    wrote notification-workflow.md",
    }

    assert format_telegram_memory_event(event) == "* memory    wrote notification-workflow.md"
