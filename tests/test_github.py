from pr_radar.github import _OpenPrsData, _clean_search_results, _to_pull_request, search_query
from pr_radar.models import CheckState, Mergeable


def raw_pr(author, comment_author):
    return {
        "id": "PR_1", "number": 7, "title": "Add login", "url": "https://example.test/7", "isDraft": False,
        "createdAt": "2026-03-01T10:00:00Z", "updatedAt": "2026-03-02T10:00:00Z", "headRefName": "feature/login",
        "repository": {"nameWithOwner": "acme/web"},
        "author": author,
        "reviewDecision": None, "mergeable": "MERGEABLE",
        "commits": {"nodes": [{"commit": {"statusCheckRollup": {"state": "FAILURE"}}}]},
        "comments": {"nodes": [{"id": "C1", "author": comment_author, "body": "hi", "createdAt": "2026-03-02T09:00:00Z", "url": "u"}]},
        "reviews": {"nodes": []},
        "reviewThreads": {"nodes": []},
    }


def parse(data):
    parsed = _OpenPrsData.model_validate(_clean_search_results(data, ["mine", "reviews"]))
    return [_to_pull_request(raw) for raw in parsed.mine.nodes]


def test_bot_and_deleted_users_are_named_clearly():
    data = {
        "viewer": {"login": "me"},
        "mine": {"nodes": [raw_pr(None, {"login": "github-actions", "__typename": "Bot"}), {}]},
        "reviews": {"nodes": []},
    }
    [pr] = parse(data)
    assert pr.author == "ghost"
    assert pr.comments[0].author == "github-actions[bot]"
    assert pr.check_state == CheckState.FAILURE
    assert pr.mergeable == Mergeable.MERGEABLE


def test_search_query_adds_org_filters():
    assert search_query("is:pr is:open", ["acme", "beta"]) == "is:pr is:open archived:false org:acme org:beta"
    assert search_query("is:pr", []) == "is:pr archived:false"
