from __future__ import annotations

import re
from typing import Any

import httpx
import structlog

from coding_eval.dataset.filters import (
    filter_failure_reasons,
    has_test_coverage,
    not_merged_after_cutoff,
    passes_all_filters,
    single_file_change,
)
from coding_eval.dataset.io import dump_tasks
from coding_eval.dataset.schema import Task

log = structlog.get_logger(__name__)

_ISSUE_REF_RE = re.compile(
    r"(?:fixes|closes|resolves)\s+#(\d+)",
    re.IGNORECASE,
)

_MERGED_SEARCH_UNTIL = "2024-12-31"


class GitHubDatasetBuilder:
    def __init__(
        self,
        github_token: str,
        repos: list[str],
        *,
        max_pr_pages: int = 10,
        max_merged_search_pages: int = 3,
        log_filter_misses: bool = False,
    ) -> None:
        self._token = github_token
        self._repos = repos
        self._max_pr_pages = max_pr_pages
        self._max_merged_search_pages = max_merged_search_pages
        self._log_filter_misses = log_filter_misses
        self._headers = {
            "Authorization": f"Bearer {github_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def fetch_closed_issues(
        self,
        repo: str,
        limit: int = 200,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> list[dict[str, Any]]:
        if client is None:
            async with self._client() as owned:
                return await self.fetch_closed_issues(repo, limit, client=owned)
        return await self._fetch_closed_issues(client, repo, limit)

    async def fetch_pr_for_issue(
        self,
        repo: str,
        issue_number: int,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> dict[str, Any] | None:
        if client is None:
            async with self._client() as owned:
                return await self.fetch_pr_for_issue(
                    repo,
                    issue_number,
                    client=owned,
                )
        owner, name = _split_repo(repo)
        pr = await self._fetch_pr_via_timeline(client, owner, name, issue_number)
        if pr is not None:
            return pr
        pr = await self._fetch_pr_via_search(client, owner, name, issue_number)
        if pr is not None:
            return pr
        return await self._fetch_pr_from_closed_pulls(
            client,
            owner,
            name,
            issue_number,
            max_pages=2,
        )

    async def build_task(
        self,
        repo: str,
        issue: dict[str, Any],
        pr: dict[str, Any],
        *,
        client: httpx.AsyncClient | None = None,
    ) -> Task | None:
        issue_number = issue.get("number")
        if not isinstance(issue_number, int):
            return None

        issue_body = issue.get("body") or ""
        if not isinstance(issue_body, str) or not issue_body.strip():
            return None

        base_commit = pr.get("base_commit")
        if not isinstance(base_commit, str) or not base_commit:
            return None

        changed_files = pr.get("changed_files", [])
        if not isinstance(changed_files, list):
            return None
        test_files = [
            f for f in changed_files if isinstance(f, str) and _is_test_path(f)
        ]
        if not test_files:
            return None

        hints = await self._fetch_hints(repo, issue_number, client=client)

        slug = repo.split("/")[-1].lower()
        task_id = f"{slug}-{issue_number:04d}"

        return Task(
            task_id=task_id,
            repo=repo,
            base_commit=base_commit,
            issue_number=issue_number,
            issue_title=str(issue.get("title") or ""),
            issue_body=issue_body.strip(),
            test_files=test_files,
            hints_text=hints,
            source="github",
        )

    async def run(self, output_path: str, limit: int = 50) -> list[Task]:
        tasks: list[Task] = []
        seen: set[tuple[str, int]] = set()
        per_repo = max(limit // max(len(self._repos), 1), limit)

        async with self._client() as client:
            for repo in self._repos:
                if len(tasks) >= limit:
                    break

                repo = await self._resolve_repo_slug(client, repo)
                log.info("dataset.fetch_issues", repo=repo)
                try:
                    issues = await self._fetch_closed_issues(
                        client,
                        repo,
                        limit=per_repo * 10,
                    )
                except httpx.HTTPError as exc:
                    log.warning("dataset.issues_failed", repo=repo, error=str(exc))
                    issues = []

                for issue in issues:
                    if len(tasks) >= limit:
                        break
                    issue_number = issue.get("number")
                    if not isinstance(issue_number, int):
                        continue
                    key = (repo, issue_number)
                    if key in seen:
                        continue
                    try:
                        pr = await self.fetch_pr_for_issue(
                            repo,
                            issue_number,
                            client=client,
                        )
                    except httpx.HTTPError as exc:
                        log.warning(
                            "dataset.pr_lookup_failed",
                            repo=repo,
                            issue_number=issue_number,
                            error=str(exc),
                        )
                        continue
                    if pr is None:
                        continue
                    if not self._accept_pair(repo, issue_number, issue, pr):
                        continue
                    built = await self.build_task(repo, issue, pr, client=client)
                    if built is None:
                        continue
                    seen.add(key)
                    tasks.append(built)
                    log.info("dataset.task_built", repo=repo, task_id=built.task_id)

                if len(tasks) >= limit:
                    continue

                discovered = await self._discover_via_merged_search(
                    client,
                    repo,
                    limit=limit - len(tasks),
                    seen=seen,
                    max_pages=self._max_merged_search_pages,
                )
                for discovered_task in discovered:
                    tasks.append(discovered_task)
                    log.info(
                        "dataset.task_built",
                        repo=repo,
                        task_id=discovered_task.task_id,
                    )

                if len(tasks) >= limit:
                    continue

                discovered_pulls = await self._discover_from_merged_pulls(
                    client,
                    repo,
                    limit=limit - len(tasks),
                    seen=seen,
                    max_pages=self._max_pr_pages,
                )
                for discovered_task in discovered_pulls:
                    tasks.append(discovered_task)
                    log.info(
                        "dataset.task_built",
                        repo=repo,
                        task_id=discovered_task.task_id,
                    )

        dump_tasks(tasks, output_path)
        log.info("dataset.written", path=output_path, n_tasks=len(tasks))
        return tasks

    def _accept_pair(
        self,
        repo: str,
        issue_number: int,
        issue: dict[str, Any],
        pr: dict[str, Any],
    ) -> bool:
        if passes_all_filters(issue, pr):
            return True
        if self._log_filter_misses:
            log.debug(
                "dataset.filter_reject",
                repo=repo,
                issue_number=issue_number,
                reasons=filter_failure_reasons(issue, pr),
            )
        return False

    async def _fetch_closed_issues(
        self,
        client: httpx.AsyncClient,
        repo: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        owner, name = _split_repo(repo)
        issues: list[dict[str, Any]] = []
        page = 1
        per_page = min(100, limit)

        while len(issues) < limit:
            resp = await client.get(
                f"/repos/{owner}/{name}/issues",
                params={
                    "state": "closed",
                    "labels": "bug",
                    "per_page": per_page,
                    "page": page,
                },
            )
            resp.raise_for_status()
            batch = resp.json()
            if not batch:
                break
            for item in batch:
                if item.get("pull_request") is not None:
                    continue
                item["_bug_query_match"] = True
                issues.append(item)
                if len(issues) >= limit:
                    break
            if len(batch) < per_page:
                break
            page += 1

        return issues[:limit]

    async def _discover_via_merged_search(
        self,
        client: httpx.AsyncClient,
        repo: str,
        *,
        limit: int,
        seen: set[tuple[str, int]],
        max_pages: int,
    ) -> list[Task]:
        if limit <= 0:
            return []

        owner, name = _split_repo(repo)
        query = (
            f"repo:{owner}/{name} is:pr is:merged "
            f"merged:2018-01-01..{_MERGED_SEARCH_UNTIL}"
        )
        tasks: list[Task] = []
        loads = 0
        max_loads = 120
        log.info("dataset.search_merged_prs", repo=repo, max_pages=max_pages)

        for page in range(1, max_pages + 1):
            if len(tasks) >= limit or loads >= max_loads:
                break
            try:
                resp = await client.get(
                    "/search/issues",
                    params={
                        "q": query,
                        "per_page": 100,
                        "page": page,
                        "sort": "updated",
                        "order": "desc",
                    },
                )
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                log.warning(
                    "dataset.merged_search_failed",
                    repo=repo,
                    page=page,
                    status=exc.response.status_code,
                )
                break

            payload = resp.json()
            items: list[dict[str, Any]] = payload.get("items", [])
            if not items:
                break

            for item in items:
                if len(tasks) >= limit or loads >= max_loads:
                    break
                pr_number = item.get("number")
                if not isinstance(pr_number, int):
                    continue
                title = str(item.get("title") or "")
                body = str(item.get("body") or "")
                if not _referenced_issue_numbers(title, body):
                    continue
                closed_at = item.get("closed_at")
                if isinstance(closed_at, str) and not not_merged_after_cutoff(
                    {"merged_at": closed_at},
                ):
                    continue
                loads += 1
                try:
                    pr = await self._load_pr(client, owner, name, pr_number)
                except httpx.HTTPError:
                    continue
                if not (
                    single_file_change(pr)
                    and has_test_coverage(pr)
                    and not_merged_after_cutoff(pr)
                ):
                    continue
                batch_tasks = await self._tasks_from_pr(
                    client,
                    repo,
                    owner,
                    name,
                    pr,
                    seen,
                    limit - len(tasks),
                )
                tasks.extend(batch_tasks)

            if len(items) < 100:
                break

        return tasks

    async def _discover_from_merged_pulls(
        self,
        client: httpx.AsyncClient,
        repo: str,
        *,
        limit: int,
        seen: set[tuple[str, int]],
        max_pages: int,
    ) -> list[Task]:
        if limit <= 0:
            return []

        owner, name = _split_repo(repo)
        tasks: list[Task] = []
        log.info("dataset.scan_merged_prs", repo=repo, max_pages=max_pages)

        for page in range(1, max_pages + 1):
            if len(tasks) >= limit:
                break
            try:
                resp = await client.get(
                    f"/repos/{owner}/{name}/pulls",
                    params={
                        "state": "closed",
                        "sort": "updated",
                        "direction": "desc",
                        "per_page": 100,
                        "page": page,
                    },
                )
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                log.warning(
                    "dataset.scan_pulls_failed",
                    repo=repo,
                    page=page,
                    status=exc.response.status_code,
                )
                break

            batch: list[dict[str, Any]] = resp.json()
            if not batch:
                break

            for summary in batch:
                if len(tasks) >= limit:
                    break
                if not isinstance(summary, dict):
                    continue
                if summary.get("merged_at") is None:
                    continue
                pr_number = summary.get("number")
                if not isinstance(pr_number, int):
                    continue
                try:
                    pr = await self._load_pr(client, owner, name, pr_number)
                except httpx.HTTPError:
                    continue
                if not (
                    single_file_change(pr)
                    and has_test_coverage(pr)
                    and not_merged_after_cutoff(pr)
                ):
                    continue
                batch_tasks = await self._tasks_from_pr(
                    client,
                    repo,
                    owner,
                    name,
                    pr,
                    seen,
                    limit - len(tasks),
                )
                tasks.extend(batch_tasks)

            if len(batch) < 100:
                break

        return tasks

    async def _tasks_from_pr(
        self,
        client: httpx.AsyncClient,
        repo: str,
        owner: str,
        name: str,
        pr: dict[str, Any],
        seen: set[tuple[str, int]],
        limit: int,
    ) -> list[Task]:
        if limit <= 0:
            return []

        tasks: list[Task] = []
        refs = _referenced_issue_numbers(
            str(pr.get("title") or ""),
            str(pr.get("body") or ""),
        )
        for issue_number in refs:
            if len(tasks) >= limit:
                break
            key = (repo, issue_number)
            if key in seen:
                continue
            try:
                issue_resp = await client.get(
                    f"/repos/{owner}/{name}/issues/{issue_number}",
                )
                issue_resp.raise_for_status()
                issue: dict[str, Any] = issue_resp.json()
            except httpx.HTTPError:
                continue
            if issue.get("pull_request") is not None:
                continue
            if not self._accept_pair(repo, issue_number, issue, pr):
                continue
            built = await self.build_task(repo, issue, pr, client=client)
            if built is None:
                continue
            seen.add(key)
            tasks.append(built)
        return tasks

    async def _fetch_pr_via_timeline(
        self,
        client: httpx.AsyncClient,
        owner: str,
        name: str,
        issue_number: int,
    ) -> dict[str, Any] | None:
        try:
            resp = await client.get(
                f"/repos/{owner}/{name}/issues/{issue_number}/timeline",
                params={"per_page": 100},
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 404:
                log.debug(
                    "dataset.timeline_failed",
                    repo=f"{owner}/{name}",
                    issue_number=issue_number,
                    status=exc.response.status_code,
                )
            return None

        events: list[dict[str, Any]] = resp.json()
        for event in events:
            if event.get("event") != "cross-referenced":
                continue
            source = event.get("source")
            if not isinstance(source, dict):
                continue
            ref_issue = source.get("issue")
            if not isinstance(ref_issue, dict):
                continue
            if ref_issue.get("pull_request") is None:
                continue
            pr_number = ref_issue.get("number")
            if not isinstance(pr_number, int):
                continue
            title = str(ref_issue.get("title") or "")
            body = str(ref_issue.get("body") or "")
            if not _references_issue(title, body, issue_number):
                continue
            return await self._load_pr(client, owner, name, pr_number)
        return None

    async def _fetch_pr_via_search(
        self,
        client: httpx.AsyncClient,
        owner: str,
        name: str,
        issue_number: int,
    ) -> dict[str, Any] | None:
        query = f"repo:{owner}/{name} is:pr is:merged closes:{issue_number}"
        try:
            resp = await client.get(
                "/search/issues",
                params={"q": query, "per_page": 10},
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code not in {403, 422}:
                log.debug(
                    "dataset.search_pr_failed",
                    repo=f"{owner}/{name}",
                    issue_number=issue_number,
                    status=exc.response.status_code,
                )
            return None

        items: list[dict[str, Any]] = resp.json().get("items", [])
        for item in items:
            pr_number = item.get("number")
            if not isinstance(pr_number, int):
                continue
            title = item.get("title") or ""
            body = item.get("body") or ""
            if not _references_issue(title, body, issue_number):
                continue
            return await self._load_pr(client, owner, name, pr_number)
        return None

    async def _fetch_pr_from_closed_pulls(
        self,
        client: httpx.AsyncClient,
        owner: str,
        name: str,
        issue_number: int,
        *,
        max_pages: int,
    ) -> dict[str, Any] | None:
        for page in range(1, max_pages + 1):
            try:
                resp = await client.get(
                    f"/repos/{owner}/{name}/pulls",
                    params={"state": "closed", "per_page": 100, "page": page},
                )
                resp.raise_for_status()
            except httpx.HTTPStatusError:
                return None

            batch: list[dict[str, Any]] = resp.json()
            if not batch:
                break

            for summary in batch:
                if not isinstance(summary, dict):
                    continue
                pr_number = summary.get("number")
                if not isinstance(pr_number, int):
                    continue
                title = str(summary.get("title") or "")
                body = str(summary.get("body") or "")
                if not _references_issue(title, body, issue_number):
                    continue
                return await self._load_pr(client, owner, name, pr_number)

        return None

    async def _load_pr(
        self,
        client: httpx.AsyncClient,
        owner: str,
        name: str,
        pr_number: int,
    ) -> dict[str, Any]:
        pr_resp = await client.get(f"/repos/{owner}/{name}/pulls/{pr_number}")
        pr_resp.raise_for_status()
        pr_data: dict[str, Any] = pr_resp.json()

        files_resp = await client.get(
            f"/repos/{owner}/{name}/pulls/{pr_number}/files",
            params={"per_page": 100},
        )
        files_resp.raise_for_status()
        files_json: list[dict[str, Any]] = files_resp.json()
        changed_files = [
            f["filename"]
            for f in files_json
            if isinstance(f.get("filename"), str)
        ]

        base = pr_data.get("base") or {}
        base_sha = base.get("sha") if isinstance(base, dict) else None

        return {
            "number": pr_number,
            "title": pr_data.get("title") or "",
            "body": pr_data.get("body") or "",
            "merged_at": pr_data.get("merged_at"),
            "base_commit": base_sha,
            "changed_files": changed_files,
        }

    async def _fetch_hints(
        self,
        repo: str,
        issue_number: int,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> str:
        owner, name = _split_repo(repo)
        if client is None:
            async with self._client() as owned:
                return await self._fetch_hints(repo, issue_number, client=owned)

        resp = await client.get(
            f"/repos/{owner}/{name}/issues/{issue_number}/comments",
            params={"per_page": 100},
        )
        resp.raise_for_status()
        comments: list[dict[str, Any]] = resp.json()

        if not comments:
            return ""

        def score(comment: dict[str, Any]) -> int:
            reactions = comment.get("reactions") or {}
            if not isinstance(reactions, dict):
                return 0
            total = reactions.get("+1", 0)
            return int(total) if isinstance(total, int) else 0

        best = max(comments, key=score)
        body = best.get("body") or ""
        if not isinstance(body, str):
            return ""
        return body[:500]

    async def _resolve_repo_slug(
        self,
        client: httpx.AsyncClient,
        repo: str,
    ) -> str:
        owner, name = _split_repo(repo)
        try:
            resp = await client.get(f"/repos/{owner}/{name}")
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()
            full_name = data.get("full_name")
            if isinstance(full_name, str) and "/" in full_name:
                if full_name != repo:
                    log.info("dataset.repo_resolved", requested=repo, resolved=full_name)
                return full_name
        except httpx.HTTPError as exc:
            log.warning("dataset.repo_resolve_failed", repo=repo, error=str(exc))
        return repo

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url="https://api.github.com",
            headers=self._headers,
            timeout=httpx.Timeout(60.0),
            follow_redirects=True,
        )


def _split_repo(repo: str) -> tuple[str, str]:
    parts = repo.split("/", maxsplit=1)
    expected_parts = 2
    if len(parts) != expected_parts or not parts[0] or not parts[1]:
        msg = f"Invalid repo slug: {repo!r}"
        raise ValueError(msg)
    return parts[0], parts[1]


def _references_issue(title: str, body: str, issue_number: int) -> bool:
    return issue_number in _referenced_issue_numbers(title, body)


def _referenced_issue_numbers(title: str, body: str) -> list[int]:
    text = f"{title}\n{body}"
    seen: set[int] = set()
    ordered: list[int] = []
    for match in _ISSUE_REF_RE.finditer(text):
        number = int(match.group(1))
        if number not in seen:
            seen.add(number)
            ordered.append(number)
    return ordered


def _is_test_path(path: str) -> bool:
    parts = path.replace("\\", "/").split("/")
    filename = parts[-1]
    return filename.startswith("test_") and filename.endswith(".py")
