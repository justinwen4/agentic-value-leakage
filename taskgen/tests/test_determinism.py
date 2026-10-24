"""Rule 4: same config -> same bytes, including commit hashes."""
from .conftest import repo_files


def test_same_cell_same_bytes(gen):
    a = gen()
    b = gen(tag="again")
    assert repo_files(a.path) == repo_files(b.path)
    assert a.meta["git"]["head"] == b.meta["git"]["head"]
    assert {k: v for k, v in a.meta.items() if k != "task_dir"} == {k: v for k, v in b.meta.items() if k != "task_dir"}
