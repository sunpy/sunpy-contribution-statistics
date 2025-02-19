import ast
import contextlib
import subprocess
import time
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import requests

from repo_stats.utilities import fill_missed_months, update_cache


class GitMetrics:
    def __init__(self, token, repo_owner, repo_name, cache_dir) -> None:
        """
        Class for getting and processing repository data (commit history,
        issues, pull requests, contributors) from GitHub for a given
        repository.

        Arguments
        ---------
        token : str
            Authorization token for GitHub queries
        repo_owner : str
            Owner (or organization) of repository on GitHub
        repo_name : str
            Name of repository on GitHub
        cache_dir : str, default=None
            Path to directory that will be populated with caches of git data
        """
        self.token = token
        self.repo_owner = repo_owner
        self.repo_name = repo_name
        self.cache_dir = cache_dir

    def get_age(self, date):
        """
        Get the 'datetime' age of a string 'date'.

        Arguments
        ---------
        date : str
            Dates with assumed string format "2024-01-01..."

        Returns
        -------
        age : 'datetime.timedelta' instance or int
            Age of the item (int if 'days_since' is True)
        """
        if date is None:
            return -1
        now = datetime.now(UTC)
        date_utc = datetime.strptime(date[:10], "%Y-%m-%d").replace(tzinfo=UTC)
        return now - date_utc

    def parse_log_line(self, line):
        """
        Break an individual 'git log' line 'line' into its component parts
        (commit hash, date, author).

        Arguments
        ---------
        line : str
            Dates with assumed string format "2024-01-01..."

        Returns
        -------
        parsed : list of str
            The commit's hash, date, author
        """
        line = line.split(",")
        return [line[ii].lstrip('"').rstrip('"\n') for ii in range(3)]

    def get_commits(self):
        """
        Obtain the commit history for a repository with 'git log', and parse
        the output.

        Returns
        -------
        all_items : list of dict
            A dictionary entry for each commit in the history, including the identifiers below in 'query'
        """
        print("\nCollecting git commit history")
        cache_file = f"{self.cache_dir}/{self.repo_name}_commits.txt"
        if not Path(cache_file).exists():
            Path(cache_file).open("w").close()
        with Path(cache_file).open() as f:
            old_items = f.readlines()
            print(f"  {len(old_items)} commits found in cache at {cache_file}")
        # NOTE: 'after' here differs from GitMetrics.get_issues_prs, as does its type in 'query' below ('String' vs. 'String!') - see https://github.com/orgs/community/discussions/24443
        # convert string to dict and get relevant key
        after = None if old_items == [] else ast.literal_eval(old_items[-1].rstrip("\n"))["endCursor"]
        # For query syntax, see https://docs.github.com/en/graphql/reference/objects#repository
        # and https://docs.github.com/en/graphql/reference/objects#commit
        # and https://docs.github.com/en/graphql/reference/objects#gitactor
        # and https://docs.github.com/en/graphql/guides/using-pagination-in-the-graphql-api
        # To quickly test a query, try https://docs.github.com/en/graphql/overview/explorer
        query = """
        query($owner: String!, $name: String!, $after: String) {
            repository(name: $name, owner: $owner) {
                ref(qualifiedName: "main") {
                    target {
                        ... on Commit {
                            history(first: 100, after: $after) {
                                pageInfo {
                                    hasNextPage
                                    endCursor
                                }

                                edges {
                                    node {
                                        oid
                                        authoredDate
                                        author {
                                            name
                                            email
                                            user {
                                                databaseId
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        """
        headers = {"Authorization": f"token {self.token}"}
        # with 'after', traverse through items (issues or PRs) from oldest to newest
        variables = {
            "owner": self.repo_owner,
            "name": self.repo_name,
            "after": after,
        }
        # must traverse through pages of items
        has_next_page = True
        new_items = []
        items_retrieved = 0
        while has_next_page is True:
            response = requests.post(
                "https://api.github.com/graphql",
                json={"query": query, "variables": variables},
                headers=headers,
                timeout=180,
            )
            if response.status_code == 200:
                result = response.json()
                try:
                    result["data"]
                except KeyError:
                    print(f"Query syntax is likely wrong. Response to query: {result}")
                    raise
                items_retrieved += len(result["data"]["repository"]["ref"]["target"]["history"]["edges"])
                time_to_reset = datetime.fromtimestamp(
                    int(response.headers["X-RateLimit-Reset"]) - time.time(),
                    tz=UTC,
                ).strftime("%M:%S")
                if len(result["data"]["repository"]["ref"]["target"]["history"]["edges"]) > 0:
                    print(
                        f"\r  Retrieved {items_retrieved} new commits (rate limit used: {response.headers['X-RateLimit-Used']} of {response.headers['X-RateLimit-Limit']} - resets in {time_to_reset})",
                        end="",
                        flush=True,
                    )
                    # store ID of the chronologically newest commit on current page, used to later reference newest item in cache
                    result["data"]["repository"]["ref"]["target"]["history"]["edges"][-1]["endCursor"] = result["data"][
                        "repository"
                    ]["ref"]["target"]["history"]["pageInfo"]["endCursor"]
                    new_items.extend(result["data"]["repository"]["ref"]["target"]["history"]["edges"])
                has_next_page = result["data"]["repository"]["ref"]["target"]["history"]["pageInfo"]["hasNextPage"]
                variables["after"] = result["data"]["repository"]["ref"]["target"]["history"]["pageInfo"]["endCursor"]
            else:
                msg = f"Query failed -- return code {response.status_code}"
                raise Exception(msg)
        # prevent last flush, without printing new line
        print(end="")
        return update_cache(cache_file, old_items, new_items)

    def get_commits_via_git_log(self, repo_local_path):
        """
        Obtain the commit history for a repository with 'git log' and a local
        copy of the repository; and parse the output.

        Arguments
        ---------
        repo_local_path : str
            Path to local copy of repository

        Returns
        -------
        dates : list of str
            Date of each commit
        author_commits : dict
            Keys are the authors and the value is a list of the commits they have contributed
        """
        print("\nCollecting git commit history")
        git_log = subprocess.run(
            args=f'git -C {repo_local_path} log --use-mailmap --date=iso-local --format="%H","%as","%aN"'.split(),
            stdout=subprocess.PIPE,
            # preserve non-English letters in names
            text=True,
            check=False,
        )
        dates = []
        authors_with_commits = defaultdict(list)
        for line in git_log.stdout.splitlines():
            commit, date, author = self.parse_log_line(line)
            dates.append(date)
            authors_with_commits[author].append(commit)
        if len(dates) == 0:
            msg = f"0 commits found for repository in git log. Check that 'repo_dir' {repo_local_path} in the .json parameter file is correct."
            raise RuntimeError(msg)
        return dates, authors_with_commits

    def process_commits(self, results, age_recent=90):
        """
        Process (obtain statistics for) git commit data.

        Arguments
        ---------
        results : list of dict
            A dictionary entry for each commit in the history (see `Git_metrics.get_commits`)
        age_recent : int, default=90
            Days before present used to categorize recent commit statistics

        Returns
        -------
        stats : dict
            Commit statistics:
                - 'age_recent_commit': the input arg 'age_recent'
                - 'unique_authors': each commit author, their number of commits and index of first commit
                - 'new_authors': list of authors with their first commit in 'age_recent'
                - 'n_recent_authors': number of authors with commits in 'age_recent'
                - 'authors_per_month': number of commit authors per month, over time
                - 'new_authors_per_month': number of new commit authors per month, over time
                - 'multi_authors_per_month': number of commit authors per month with >1 commit that month, over time
        """
        dates, authors, user_ids = [], [], []
        bots = [
            "dependabot[bot]",
            "github-actions",
            "github-actions[bot]",
            "meeseeksmachine",
            "odidev",
            "pre-commit-ci[bot]",
            "codetriage-readme-bot",
            "unknown",
        ]
        for ii in results:
            if ii["node"]["author"]["name"] not in bots:
                dates.append(ii["node"]["authoredDate"])
                authors.append(ii["node"]["author"]["name"])
                # some authors have None in 'user' field
                try:
                    user_ids.append(ii["node"]["author"]["user"]["databaseId"])
                except TypeError:
                    user_ids.append(ii["node"]["author"]["name"])
        print(f"  {len(dates)} total commits")
        # assuming we don't have a .mailmap file to connect unique authors to multiple versions of their name and/or emails,
        # use their GitHub IDs (likely won't catch all variations)
        unique_ids = np.unique(user_ids, return_index=True, return_counts=True)
        # IDs that occur in commit history at least twice
        unique_ids_repeat = [x for i, x in enumerate(unique_ids[0]) if unique_ids[2][i] > 1]
        # set author name for all instances of the ID repeat to their name at last (most recent) instance
        for i in unique_ids_repeat:
            idxs = np.where(np.array(user_ids) == i)[0]
            for j in idxs:
                authors[j] = authors[idxs[-1]]
        commits_for_each_author = Counter(authors)
        dates_strip_day = [d[:7] for d in dates]
        zipped = list(zip(dates_strip_day, authors, strict=False))
        unique_month_author_pairs = np.unique(zipped, axis=0, return_counts=True)
        # number of unique commit authors per month
        authors_per_month = np.unique([x[0] for x in unique_month_author_pairs[0]], axis=0, return_counts=True)
        # possible that not every month has commits,
        # so insert months without commits and 0 for their number of authors
        authors_per_month = fill_missed_months(authors_per_month)
        # number of authors per month with >1 commit that month
        multi_authors_per_month = np.unique(
            [x[0] for i, x in enumerate(unique_month_author_pairs[0]) if unique_month_author_pairs[1][i] > 1],
            axis=0,
            return_counts=True,
        )
        multi_authors_per_month = fill_missed_months(multi_authors_per_month)
        # '*last*' and '*first*' variables assume the git log is in reverse chronological order
        unique_authors_last_commit = np.unique(authors, return_index=True, return_counts=True)
        unique_authors_first_commit = np.unique(authors[::-1], return_index=True, return_counts=True)
        # last and first commit dates per author
        date_last_commit = [dates[i] for i in unique_authors_last_commit[1]]
        date_first_commit = [dates[::-1][i] for i in unique_authors_first_commit[1]]
        # number of new authors per month
        new_authors_per_month = np.unique([x[:7] for x in date_first_commit], return_counts=True)
        new_authors_per_month = fill_missed_months(new_authors_per_month)
        n_recent_authors, new_authors = 0, []
        for ii, jj in enumerate(unique_authors_last_commit[0]):
            last_commit_age = self.get_age(date_last_commit[ii])
            first_commit_age = self.get_age(date_first_commit[ii])
            if last_commit_age.days <= age_recent:
                n_recent_authors += 1
                # authors with their first commit(s) in this period
                if first_commit_age.days <= age_recent:
                    new_authors.append(str(jj))
        return {
            "age_recent_commit": age_recent,
            "unique_authors": unique_authors_first_commit,
            "new_authors": new_authors,
            "n_recent_authors": n_recent_authors,
            "authors_per_month": authors_per_month,
            "new_authors_per_month": new_authors_per_month,
            "multi_authors_per_month": multi_authors_per_month,
            "commits_for_each_author": commits_for_each_author,
        }

    def get_issues_prs(self, item_type):
        """
        Obtain the issue or pull request history for a GitHub repository by
        querying the GraphQL API.

        Arguments
        ---------
        item_type : str
            One of ['issues', 'pullRequests'] to obtain the corresponding history

        Returns
        -------
        all_items : list of dict
            A dictionary entry for each issue or pull request in the history, including the identifiers below in 'query'
        """
        print(f"\nCollecting GitHub {item_type} history")
        supported_items = ["issues", "pullRequests"]
        if item_type not in supported_items:
            msg = f"item_type {item_type} invalid; must be one of {supported_items}"
            raise ValueError(msg)
        cache_file = f"{self.cache_dir}/{self.repo_name}_{item_type}.txt"
        if not Path(cache_file).exists():
            Path(cache_file).open("w").close()
        with Path(cache_file).open() as f:
            old_items = f.readlines()
            print(f"  {len(old_items)} {item_type} found in cache at {cache_file}")
        after = "" if old_items == [] else ast.literal_eval(old_items[-1].rstrip("\n"))["endCursor"]
        # For query syntax, see https://docs.github.com/en/graphql/reference/objects#repository
        # and https://docs.github.com/en/graphql/reference/objects#issue
        # and https://docs.github.com/en/graphql/reference/objects#pullrequest
        # and https://docs.github.com/en/graphql/guides/using-pagination-in-the-graphql-api
        # To quickly test a query, try https://docs.github.com/en/graphql/overview/explorer
        query = (
            """
        query($owner: String!, $name: String!, $after: String!) {
            repository(owner: $owner, name: $name) {
                """
            + item_type
            + """(first: 100, after: $after) {
                    totalCount

                    pageInfo {
                        hasNextPage
                        endCursor
                    }

                    edges {
                        node {
                            number
                            state
                            createdAt
                            updatedAt
                            closedAt

                            labels(first: 25) {
                                edges {
                                    node {
                                        name
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        """
        )
        headers = {"Authorization": f"token {self.token}"}
        # with 'after', traverse through items (issues or PRs) from oldest to newest
        variables = {
            "owner": self.repo_owner,
            "name": self.repo_name,
            "after": after,
        }
        # must traverse through pages of items
        has_next_page = True
        new_items = []
        items_retrieved = 0
        while has_next_page is True:
            response = requests.post(
                "https://api.github.com/graphql",
                json={"query": query, "variables": variables},
                headers=headers,
                timeout=180,
            )
            if response.status_code == 200:
                result = response.json()
                try:
                    result["data"]
                except KeyError:
                    print(f"Query syntax is likely wrong. Response to query: {result}")
                    raise
                items_retrieved += len(result["data"]["repository"][item_type]["edges"])
                items_total = result["data"]["repository"][item_type]["totalCount"]
                time_to_reset = datetime.fromtimestamp(
                    int(response.headers["X-RateLimit-Reset"]) - time.time(),
                    tz=UTC,
                ).strftime("%M:%S")
                if len(result["data"]["repository"][item_type]["edges"]) > 0:
                    print(
                        f"\r  Retrieved {items_retrieved} new of {items_total} total {item_type} (rate limit used: {response.headers['X-RateLimit-Used']} of {response.headers['X-RateLimit-Limit']} - resets in {time_to_reset})",
                        end="",
                        flush=True,
                    )
                    # store ID of the chronologically newest item (issue or PR) on current page, used to later reference newest item in cache
                    result["data"]["repository"][item_type]["edges"][-1]["endCursor"] = result["data"]["repository"][
                        item_type
                    ]["pageInfo"]["endCursor"]
                    new_items.extend(result["data"]["repository"][item_type]["edges"])
                has_next_page = result["data"]["repository"][item_type]["pageInfo"]["hasNextPage"]
                variables["after"] = result["data"]["repository"][item_type]["pageInfo"]["endCursor"]
            else:
                msg = f"Query failed -- return code {response.status_code}"
                raise Exception(msg)
        # prevent last flush, without printing new line
        print(end="")
        return update_cache(cache_file, old_items, new_items)

    def process_issues_prs(self, results, items, labels, age_recent=90):
        """
        Process (obtain statistics for) and aggregate issue and pull request
        data in 'results'.

        Arguments
        ---------
        results : list of dict
            A dictionary entry for each issue or pull request in the history (see `git_metrics.get_issues_prs`)
        items : list of str
            Names for the dictionary entries in the return 'issues_prs'
        labels : list of str
            GitHub labels (those added to an issue or pull request) to obtain additional statistics
        age_recent : int, default=90
            Days before present used to categorize recent issue and pull request statistics

        Returns
        -------
        issues_prs : list of dict
            Statistics for issues and separately for pull requests:
                - 'age_recent': the input arg 'age_recent'
                - 'recent_open': number of items (issues or pull requests) opened in 'age_recent'
                - 'recent_close': number of items closed in 'age_recent'
                - 'open_per_month': number of items opened per month, over time
                - 'close_per_month': number of items closed per month, over time
                - 'label_open': the input arg 'labels' and the number of currently open items with each label
        """
        issues_prs = {}
        for hh, ii in enumerate(results):
            recent_open, recent_close, date_open, date_close = 0, 0, [], []
            label_open_items = np.zeros(len(labels))
            for jj in ii:
                # store dates as year-month e.g. '2024-01'
                date_open.append(jj["node"]["createdAt"][:7])
                if jj["node"]["state"] != "OPEN":
                    date_close.append(jj["node"]["closedAt"][:7])
                # store age as days before present
                created_age = self.get_age(jj["node"]["createdAt"])
                if created_age != -1:
                    created_age = created_age.days
                    if created_age <= age_recent:
                        recent_open += 1
                closed_age = self.get_age(jj["node"]["closedAt"])
                if closed_age != -1:
                    closed_age = closed_age.days
                    if closed_age <= age_recent:
                        recent_close += 1
                if jj["node"]["state"] == "OPEN":
                    for kk in jj["node"]["labels"]["edges"]:
                        with contextlib.suppress(ValueError):
                            label_open_items[labels.index(kk["node"]["name"])] += 1
            open_per_month = np.unique(date_open, return_counts=True)
            close_per_month = np.unique(date_close, return_counts=True)
            # not every month has newly opened/closed issues/PRs,
            # so insert missed months
            open_per_month = fill_missed_months(open_per_month)
            close_per_month = fill_missed_months(close_per_month)
            issues_prs[items[hh]] = {
                "age_recent": age_recent,
                "recent_open": recent_open,
                "recent_close": recent_close,
                "open_per_month": open_per_month,
                "close_per_month": close_per_month,
                "label_open": dict(zip(labels, label_open_items, strict=False)),
            }
        return issues_prs
