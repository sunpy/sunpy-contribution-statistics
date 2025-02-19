import argparse
import json
from collections import Counter
from pathlib import Path

import repo_stats
from repo_stats.citation_metrics import ADSCitations
from repo_stats.git_metrics import GitMetrics
from repo_stats.plot import author_plot, author_time_plot, citation_plot, issue_pr_time_plot, open_issue_pr_plot
from repo_stats.user_stats import StatsImage

repo_stats_path = Path(repo_stats.__file__).parent


def parse_parameters(*args):
    """
    Read the repository and citation targets and the analysis parameters from a
    .json parameter file.

    Parameters
    ----------
    *args : list of str
        Simulates the command line arguments

    Returns
    -------
    params : dict
        Parameters used by the analysis
    """
    default_param_file = f"{repo_stats_path}/parameters.json"
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-a",
        "--ads_token",
        type=str,
        required=True,
    )
    parser.add_argument(
        "-g",
        "--git_token",
        type=str,
        required=True,
    )
    parser.add_argument(
        "-p",
        "--parameter_file",
        type=str,
        default=default_param_file,
        required=False,
    )
    parser.add_argument(
        "-c",
        "--cache_dir",
        type=str,
        required=False,
    )
    args = parser.parse_args(*args)
    with Path(args.parameter_file).open() as f:
        params = json.load(f)
    params["ads_token"], params["git_token"], params["cache_dir"] = (
        args.ads_token,
        args.git_token,
        args.cache_dir,
    )
    if params["cache_dir"] is None:
        params["cache_dir"] = f"{repo_stats_path}/../cache"
    Path(params["cache_dir"]).mkdir(parents=True, exist_ok=True)
    if params["template_image"] is None:
        params["template_image"] = [
            f"{repo_stats_path}/../dashboard_template/user_stats_template_transparent.png",
            f"{repo_stats_path}/../dashboard_template/user_stats_template_dark.png",
            f"{repo_stats_path}/../dashboard_template/user_stats_template_light.png",
        ]
    params["template_image"] = list(params["template_image"])
    params["font"] = f"{repo_stats_path}/../dashboard_template/Jost[wght].ttf"
    return params


def main(*args):
    """
    Run the citation and repository statistics analysis.

    Parameters
    ----------
    *args : list of str
        Simulates the command line arguments
    """
    base_params = parse_parameters(*args)
    total_commit_stats = {}
    for repo in base_params["repos"]:
        repo_name = repo["repo_name"]
        cache_dir = f"{base_params['cache_dir']}/{repo_name}"
        Path(cache_dir).mkdir(parents=True, exist_ok=True)
        print(f"\nAnalyzing {repo_name}")
        if "bibs" in repo:
            cites = ADSCitations(base_params["ads_token"], cache_dir)
            cite_stats = cites.aggregate_citations(repo["bibs"], base_params["ads_metrics"])
            citation_plot(cite_stats, repo_name, cache_dir, repo["bib_names"])
        gits = GitMetrics(
            base_params["git_token"],
            base_params["repo_owner"],
            repo_name,
            cache_dir,
        )
        commits = gits.get_commits()
        commit_stats = gits.process_commits(commits, base_params["age_recent_commit"])
        total_commit_stats[repo_name] = commit_stats["commits_for_each_author"]
        issues = gits.get_issues_prs("issues")
        prs = gits.get_issues_prs("pullRequests")
        if "labels" not in repo:
            repo["labels"] = []
        issue_pr_stats = gits.process_issues_prs(
            [issues, prs],
            ["issues", "pullRequests"],
            repo["labels"],
            base_params["age_recent_issue_pr"],
        )
        all_stats = {**cite_stats, **commit_stats, **issue_pr_stats}
        print("\nUpdating dashboard image with stats")
        for ii in base_params["template_image"]:
            userstatsimage = StatsImage(ii, base_params["font"])
            userstatsimage.update_image(all_stats, repo_name, cache_dir)
        author_plot(
            commit_stats,
            base_params["repo_owner"],
            repo_name,
            cache_dir,
        )
        author_time_plot(
            commit_stats,
            base_params["repo_owner"],
            repo_name,
            cache_dir,
            base_params["window_avg"],
        )
        if "issues" in issue_pr_stats:
            open_issue_pr_plot(issue_pr_stats, repo_name, cache_dir)
        issue_pr_time_plot(
            issue_pr_stats,
            base_params["repo_owner"],
            repo_name,
            cache_dir,
            base_params["window_avg"],
        )
    total_commit_stats["commits_for_each_author"] = Counter()
    for counts in total_commit_stats.values():
        total_commit_stats["commits_for_each_author"] += counts
    author_plot(
        total_commit_stats,
        base_params["repo_owner"],
        "Every Repository",
        cache_dir,
        commit_number=50,
    )


if __name__ == "__main__":
    main()
