from callbridge import align, project
from callbridge.summarize import chunk_lines


def w(s, e, word):
    return {"start": s, "end": e, "word": word}


def test_assign_speaker_overlap_and_nearest():
    turns = [(0.0, 2.0, "N1"), (2.5, 5.0, "N2")]
    assert align.assign_speaker(0.5, 1.0, turns) == "N1"
    assert align.assign_speaker(1.8, 3.5, turns) == "N2"      # más solape con N2
    assert align.assign_speaker(2.1, 2.3, turns) == "N1"      # hueco: el más cercano
    assert align.assign_speaker(2.35, 2.45, turns) == "N2"
    assert align.assign_speaker(0, 1, []) is None


def test_relabel_by_first_appearance():
    turns, labels = align.relabel_by_appearance([(5, 6, 0), (1, 2, 3), (3, 4, 0)])
    assert labels == ["N1", "N2"]
    assert turns == [(1, 2, "N1"), (3, 4, "N2"), (5, 6, "N2")]


def test_split_by_speaker_cuts_segment_at_speaker_change():
    seg = {"start": 0, "end": 4, "text": " hola qué tal fine thanks", "lang": "es",
           "words": [w(0, .5, " hola"), w(.5, 1, " qué"), w(1, 1.5, " tal"), w(2.2, 3, " fine"), w(3, 4, " thanks")]}
    out = align.split_by_speaker([seg], [(0, 1.8, "N1"), (2, 4, "N2")])
    assert [(o["speaker"], o["text"]) for o in out] == [("N1", "hola qué tal"), ("N2", "fine thanks")]
    assert out[1]["start"] == 2.2 and out[1]["end"] == 4


def test_smoothing_removes_single_word_flip():
    seg = {"start": 0, "end": 3, "text": "a b c",
           "words": [w(0, 1, " a"), w(1, 1.3, " b"), w(1.3, 3, " c")]}
    out = align.split_by_speaker([seg], [(0, 1.1, "N1"), (1.1, 1.3, "N2"), (1.3, 3, "N1")])
    assert len(out) == 1 and out[0]["speaker"] == "N1"


def test_segment_without_words_uses_overlap():
    out = align.split_by_speaker([{"start": 3, "end": 4, "text": "x", "words": []}], [(2.5, 5, "N2")])
    assert out[0]["speaker"] == "N2"


def _proj():
    p = project.empty_project("id", "Reunión", "audio.wav")
    p["duration"] = 75
    p["speakers"] = [{"id": "yo", "label": "Yo"}, {"id": "N1", "label": "Marta"}]
    p["segments"] = [
        {"id": "a", "speaker": "N1", "start": 3, "end": 5, "text": "Hola."},
        {"id": "b", "speaker": "yo", "start": 0, "end": 2, "text": "Buenas."},
        {"id": "c", "speaker": "N1", "start": 5.2, "end": 6, "text": "¿Empezamos?"},
        {"id": "d", "speaker": "yo", "start": 65, "end": 66, "text": "Vale."},
    ]
    p["summary"] = "### Resumen\nTodo bien."
    return p


def test_transcript_groups_consecutive_turns_and_uses_labels():
    lines = project.transcript_lines(_proj())
    assert lines == ["[00:00] Yo: Buenas.", "[00:03] Marta: Hola. ¿Empezamos?", "[01:05] Yo: Vale."]


def test_exports():
    p = _proj()
    md = project.export_md(p)
    assert "## Resumen" in md and "**[00:03] Marta:** Hola. ¿Empezamos?" in md
    srt = project.export_srt(p)
    assert srt.startswith("1\n00:00:00,000 --> 00:00:02,000\nYo: Buenas.")
    assert "4\n00:01:05,000 --> 00:01:06,000" in srt


def test_save_load_roundtrip(tmp_path):
    p = _proj()
    project.save_project(tmp_path, p)
    assert project.load_project(tmp_path) == p


def test_chunk_lines_respects_budget():
    lines = [f"línea {i} " + "x " * 20 for i in range(50)]
    count = lambda t: len(t.split())  # noqa: E731
    chunks = chunk_lines(lines, count, 100)
    assert len(chunks) > 1
    assert all(count(c) <= 100 + 5 for c in chunks)
    assert "\n".join(chunks).count("línea") == 50
    big = chunk_lines(["palabra " * 500], count, 100)
    assert all(count(c) <= 100 for c in big) and sum(count(c) for c in big) == 500


def test_export_claude():
    p = _proj()
    p["speakers"].append({"id": "N2", "label": "N2"})
    p["segments"].append({"id": "e", "speaker": "N2", "start": 70, "end": 71, "text": "ok", "flag": "posible eco"})
    md = project.export_claude(p)
    assert md.startswith("<!-- callbridge-transcript v1")
    assert "- **Yo**: quien grabó la llamada" in md
    assert "- **Marta**: identificado por el usuario" in md
    assert "- **N2**: sin identificar" in md
    assert "[00:03] Marta: Hola. ¿Empezamos?" in md
    assert "[01:10] N2: ⚠ ok" in md and "1 frase(s) marcadas" in md
