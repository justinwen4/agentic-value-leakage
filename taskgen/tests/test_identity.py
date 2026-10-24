"""Rule 3: same cell, different entity -> byte-identical after reverse substitution."""
from .conftest import git_log, repo_files, reverse_substitute

PAIRS = {
    "lab_eval": [("ambervale", "anthropic"), ("oxfam", "kestrel"), ("meta", "google")],
    "charity_program": [
        ("brightwater", "oxfam"),
        ("oakhurst", "unicef"),
        ("wrenfield", "givedirectly"),
    ],
}


def _normalized(generated) -> dict[str, str]:
    files = repo_files(generated.path)
    return {
        reverse_substitute(rel, generated.entity): reverse_substitute(data.decode(), generated.entity)
        for rel, data in files.items()
    }


def test_label_swap_identity_working_tree(gen, template):
    for a_key, b_key in PAIRS[template]:
        a, b = gen(a_key), gen(b_key)
        na, nb = _normalized(a), _normalized(b)
        assert set(na) == set(nb), (a_key, b_key, set(na) ^ set(nb))
        for rel in na:
            assert na[rel] == nb[rel], f"{rel} differs between {a_key} and {b_key} after reverse substitution"


def test_label_swap_identity_git_log(gen, template):
    for a_key, b_key in PAIRS[template]:
        a, b = gen(a_key), gen(b_key)
        la = reverse_substitute(git_log(a.path), a.entity)
        lb = reverse_substitute(git_log(b.path), b.entity)
        assert la == lb, f"git log differs between {a_key} and {b_key}"


def test_no_unfilled_placeholders(gen):
    for rel, data in repo_files(gen().path).items():
        assert b"{{" not in data, f"unfilled placeholder in {rel}"
