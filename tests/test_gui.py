import pytest

from placefinder import gui


def test_custom_search_explains_missing_files(tmp_path, monkeypatch):
    monkeypatch.setattr(gui, "ROOT", tmp_path)
    with pytest.raises(ValueError, match="Choose a recording"):
        gui.run_job(["", "", "", "", "", ""], lambda _: None)
