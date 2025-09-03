#!/usr/bin/env python3
"""
PR Conflict Checker

This script checks for conflicts between open Pull Requests in a GitHub repository.
It generates a matrix visualization showing which PRs conflict with each other.

Usage:
    python pr_conflict_check.py <repo_url> <github_token>

Example:
    python pr_conflict_check.py https://github.com/owner/repo ghp_XXXXXX
"""

import os
import sys
import argparse
import tempfile
import subprocess
import matplotlib.pyplot as plt
import numpy as np
from github import Github
from github.GithubException import GithubException
from contextlib import contextmanager
from datetime import datetime


@contextmanager
def pushd(new_dir):
    previous_dir = os.getcwd()
    os.chdir(new_dir)
    try:
        yield
    finally:
        os.chdir(previous_dir)

def parse_args():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(description='Check for conflicts between GitHub PRs')
    parser.add_argument('repo_url', help='GitHub repository URL (e.g., https://github.com/owner/repo)')
    parser.add_argument('github_token', help='GitHub personal access token')
    parser.add_argument('--base-branch', help='Base branch to check PRs against (default: repository default branch)')
    return parser.parse_args()

def get_github_client(token):
    """Create authenticated GitHub client"""
    return Github(token)

def get_repo_info(repo_url):
    """Extract owner and repo name from URL"""
    # Handle different URL formats
    if repo_url.endswith('.git'):
        repo_url = repo_url[:-4]
    if repo_url.endswith('/'):
        repo_url = repo_url[:-1]

    # Extract owner and repo from URL
    parts = repo_url.split('/')
    if len(parts) < 2:
        raise ValueError('Invalid repository URL format')
    return parts[-2], parts[-1]

def get_open_prs(github_client, owner, repo, base_branch=None):
    """Get list of open PRs from GitHub targeting specific base branch"""
    repo_obj = github_client.get_repo(f"{owner}/{repo}")
    prs = repo_obj.get_pulls(state='open')

    # Filter PRs targeting the specified base branch and not already conflicting
    filtered_prs = []
    for pr in prs:
        if pr.draft:
            continue
        if base_branch and pr.base.ref != base_branch:
            continue
        if pr.mergeable is False:  # Skip PRs that are already conflicting
            continue
        filtered_prs.append(pr)

    return filtered_prs


logFile = open('subprocess_log.txt', 'a', encoding="utf8")

def run_subprocess_and_log(cmd):
    """Run subprocess command, log subprocess command and its output to a file"""
    global logFile
    result = subprocess.run(cmd, check=False, capture_output=True, text=True)
    returncode = result.returncode
    output = result.stdout
    error = result.stderr
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    logFile.write(f"\n[{timestamp}] Command: {' '.join(cmd)}\n")
    logFile.write(f"Return Code:{returncode}\n")
    if output:
        logFile.write(f"Output:\n{output}\n")
    if error:
        logFile.write(f"Error:\n{error}\n")
    return result

def clone_repo(repo_url, clone_dir):
    """Clone repository to local directory"""
    cmd = ['git', 'clone', repo_url, clone_dir]
    run_subprocess_and_log(cmd)

def fetch_pr_branches(repo_dir, prs):
    """Fetch all PR branches to local repository, handling forks"""
    with pushd(repo_dir):
        for pr in prs:
            # Use PR_<number> as the local branch name for all PRs
            local_branch = f"PR_{pr.number}"

            # Check if this is a fork (different repo)
            if pr.head.repo.full_name != pr.base.repo.full_name:
                # For forks, we need to fetch from the fork's URL
                fork_url = pr.head.repo.clone_url
                run_subprocess_and_log(['git', 'fetch', fork_url, f"{pr.head.ref}:{local_branch}"])
            else:
                # For same repo, fetch normally
                run_subprocess_and_log(['git', 'fetch', 'origin', f"{pr.head.ref}:{local_branch}"])

def get_branch_name(pr):
    """Get the local branch name for a PR"""
    return f"PR_{pr.number}"

def detect_conflicts(repo_dir, prs):
    """Detect conflicts between PRs using git merge with temporary branches"""
    conflict_matrix = []

    # First fetch all PR branches
    fetch_pr_branches(repo_dir, prs)

    for i, pr1 in enumerate(prs):
        row = []
        for j, pr2 in enumerate(prs):
            if i == j:
                row.append(False)  # No self-conflict
                continue

            # Get the correct branch names (handling forks)
            branch1 = get_branch_name(pr1)
            branch2 = get_branch_name(pr2)

            # Create a unique temporary branch name
            temp_branch = f"temp_conflict_check_{i}_{j}"

            with pushd(repo_dir):
                # Clean any previous merge state
                run_subprocess_and_log(['git', 'merge', '--abort'])

                # Create temporary branch from base
                run_subprocess_and_log(['git', 'checkout', '-b', temp_branch, pr1.base.ref])

                # First merge pr1
                run_subprocess_and_log(['git', 'merge', branch1])

                # Then merge pr2
                merge_result = run_subprocess_and_log(['git', 'merge', branch2])

                # Check if second merge had conflicts
                merge_success = merge_result.returncode == 0
                row.append(not merge_success)  # True if conflict (merge failed)

                # Clean up
                run_subprocess_and_log(['git', 'checkout', pr1.base.ref])
                run_subprocess_and_log(['git', 'branch', '-D', temp_branch])

        conflict_matrix.append(row)

    return conflict_matrix

def visualize_conflicts(prs, conflict_matrix, output_file):
    """Generate visualization of conflict matrix"""
    n = len(prs)
    fig, ax = plt.subplots(figsize=(max(8, n), max(8, n)))

    # Create heatmap
    cax = ax.matshow(conflict_matrix, cmap='Reds')

    # Set up axes
    ax.set_xticks(range(n))
    ax.set_yticks(range(n))
    ax.set_xticklabels([f"#{pr.number}" for pr in prs], rotation=90)
    ax.set_yticklabels([f"#{pr.number}" for pr in prs])

    # Add colorbar
    fig.colorbar(cax)

    # Add title and labels
    plt.title('PR Conflict Matrix')
    plt.xlabel('Target PR')
    plt.ylabel('Base PR')

    # Save to file
    plt.tight_layout()
    plt.savefig(output_file)
    plt.close()

def get_default_branch(repo_dir):
    """Get the default branch of the repository"""
    with pushd(repo_dir):
        result = run_subprocess_and_log(['git', 'symbolic-ref', 'refs/remotes/origin/HEAD'])
        # Extract branch name from refs/remotes/origin/<branch>
        return result.stdout.strip().split('/')[-1]

def main():
    """Main function"""
    args = parse_args()

    # Extract repo info
    owner, repo = get_repo_info(args.repo_url)

    # Create GitHub client
    github_client = get_github_client(args.github_token)

    # Create temporary directory for repo clone
    with tempfile.TemporaryDirectory() as temp_dir:
        print(f"Cloning repository to {temp_dir}...")
        clone_repo(args.repo_url, temp_dir)

        # Determine base branch
        if args.base_branch:
            base_branch = args.base_branch
            print(f"Using specified base branch: {base_branch}")
        else:
            base_branch = get_default_branch(temp_dir)
            print(f"Using repository default branch: {base_branch}")

        # Get open PRs targeting the base branch
        print(f"Fetching open PRs for {owner}/{repo} targeting {base_branch}...")
        prs = get_open_prs(github_client, owner, repo, base_branch)
        print(f"Found {len(prs)} open PRs targeting {base_branch}")

        if len(prs) < 2:
            print("Need at least 2 PRs to check for conflicts")
            return

        # Detect conflicts
        print("Detecting conflicts between PRs...")
        conflict_matrix = detect_conflicts(temp_dir, prs)

        # Visualize results
        print("Generating visualization...")
        visualize_conflicts(prs, conflict_matrix, 'conflict_matrix.png')
        print("Conflict matrix saved to conflict_matrix.png")

if __name__ == '__main__':
    main()
    logFile.close()