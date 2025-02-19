# SunPy Project Stats

Functionality to generate git statistics (e.g.m commits, issues, pull requests) of a repository using GitHub's GraphQL API, and citation statistics using the NASA ADS publication database's API.

Produces text files of processed data, and images of summary statistics and plots.
The images are designed to be used in a README or documentation.

Orginally written for repositories in [The Astropy Project](https://github.com/astropy) and [their version](https://github.com/astropy/repo_stats).
This version has been generalized for a list of repositries and by updating the input file `parameters.json` (see `parameter_descriptions.json`), you can run this on your own.
Essential parameters to update: `repo_owner` and the `repos` section.

Run with

```bash
python -m repo_stats.runner -a "<ADS_TOKEN>" -g "<GITHUB_TOKEN>"
```

where the tokens are for access to the [NASA ADS API](https://ui.adsabs.harvard.edu/help/api/) and the [GitHub GraphQL API](https://docs.github.com/en/graphql/guides/forming-calls-with-graphql).

For current output files, see the `cache` branch.

**Borrowed from https://github.com/astropy/repo_stats with much love.**
