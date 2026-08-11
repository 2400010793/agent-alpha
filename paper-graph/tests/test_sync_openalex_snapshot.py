import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "sync_openalex_snapshot.py"
SPEC = importlib.util.spec_from_file_location("sync_openalex_snapshot", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_stratified_files_includes_manifest_endpoints() -> None:
    files = [{"url": str(index)} for index in range(10)]
    assert MODULE.stratified_files(files, 3) == [files[0], files[4], files[9]]


def test_one_stratified_file_uses_middle_not_oldest() -> None:
    files = [{"url": str(index)} for index in range(9)]
    assert MODULE.stratified_files(files, 1) == [files[4]]


def test_manifest_shards_are_disjoint_and_complete() -> None:
    files = [{"url": str(index)} for index in range(10)]
    shards = [MODULE.sharded_files(files, index, 4) for index in range(4)]

    assert shards == [
        [files[0], files[4], files[8]],
        [files[1], files[5], files[9]],
        [files[2], files[6]],
        [files[3], files[7]],
    ]
    assert sorted(item["url"] for shard in shards for item in shard) == [
        str(index) for index in range(10)
    ]


def test_manifest_shard_rejects_invalid_index() -> None:
    files = [{"url": "0"}]

    try:
        MODULE.sharded_files(files, 4, 4)
    except ValueError as error:
        assert "shard index" in str(error)
    else:
        raise AssertionError("invalid shard index was accepted")
