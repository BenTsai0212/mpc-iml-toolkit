"""The README troubleshooting section (#127): in both languages, linked from the walkthrough."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

SECTIONS = {
    "README.md": ("## Troubleshooting", "(#troubleshooting)", "## Play in 20 minutes"),
    "README.zh-TW.md": ("## 疑難排解", "(#疑難排解)", "## 20 分鐘開始演奏"),
}


def section(name: str, heading: str) -> str:
    text = (ROOT / name).read_text()
    start = text.index(heading + "\n")
    end = text.index("\n## ", start + 1)
    return text[start:end]


@pytest.mark.parametrize("name", sorted(SECTIONS))
def test_troubleshooting_section_is_linked_from_the_walkthrough(name: str) -> None:
    heading, anchor, walkthrough = SECTIONS[name]
    assert anchor in section(name, walkthrough)
    text = section(name, heading)
    for word in ("mpc-iml", "connect", "l1", "wrong_state", "amount", "uv run mpc-iml"):
        assert f"`{word}`" in text
    assert "#76" in text


def test_troubleshooting_sections_say_the_same_things() -> None:
    texts = [section(name, SECTIONS[name][0]) for name in sorted(SECTIONS)]
    rows = [len(re.findall(r"^\| ", text, re.M)) for text in texts]
    commands = [sorted(re.findall(r"`([^`]+)`", text)) for text in texts]
    links = [len(re.findall(r"\]\(#", text)) for text in texts]
    assert rows[0] == rows[1] >= 9
    assert commands[0] == commands[1]
    assert links[0] == links[1]
