from paper_graph.jsonl import read_jsonl, write_jsonl


def test_jsonl_round_trip(tmp_path) -> None:
    path = tmp_path / "records.jsonl"
    write_jsonl(path, [{"id": "a"}, {"id": "b", "value": 2}])
    assert list(read_jsonl(path)) == [{"id": "a"}, {"id": "b", "value": 2}]
