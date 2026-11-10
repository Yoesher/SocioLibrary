"""Reciprocal rank fusion; source scores need not use the same scale."""
def reciprocal_rank_fusion(*rankings, k=60):
    scores, records = {}, {}
    for ranking in rankings:
        seen = set()
        for rank, row in enumerate(ranking, 1):
            identity = row["id"]
            if identity in seen:
                continue
            seen.add(identity)
            records[identity] = row
            scores[identity] = scores.get(identity, 0) + 1 / (k + rank)
    return [dict(records[key], score=scores[key]) for key in sorted(scores, key=lambda key: (-scores[key], key))]
