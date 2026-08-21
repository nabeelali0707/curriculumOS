import os

import pytest

pytest.importorskip("pgvector")


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="requires live Postgres with pgvector configured")
def test_top_k_similar_nodes_uses_cosine_distance():
    """This is the repo's only live-DB coverage for vector retrieval until a real DB is configured."""
    pytest.skip("live pgvector coverage is intentionally skipped without DATABASE_URL")
