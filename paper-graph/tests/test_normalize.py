from paper_graph.normalize import canonical_paper_id, normalize_arxiv_id


def test_normalize_arxiv_url_and_version() -> None:
    assert normalize_arxiv_id("https://arxiv.org/abs/2401.01234v2") == "2401.01234"
    assert normalize_arxiv_id("arXiv:2401.01234") == "2401.01234"


def test_canonical_id_precedence() -> None:
    assert canonical_paper_id(arxiv="2401.01234", doi="10.1/example") == "arxiv:2401.01234"
    assert canonical_paper_id(doi="https://doi.org/10.1/Example") == "doi:10.1/example"
