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

    # Filter PRs targeting the specified base branch
    if base_branch:
        prs = [pr for pr in prs if pr.base.ref == base_branch and not pr.draft]
    else:
        prs = [pr for pr in prs if not pr.draft]

    return prs

def clone_repo(repo_url, clone_dir):
    """Clone repository to local directory"""
    subprocess.run(['git', 'clone', repo_url, clone_dir], check=True)

def checkout_pr_branch(repo_dir, pr_branch):
    """Checkout a PR branch"""
    os.chdir(repo_dir)
    subprocess.run(['git', 'checkout', pr_branch], check=True)

def merge_branches(repo_dir, base_branch, target_branch):
    """Attempt to merge target branch into base branch"""
    os.chdir(repo_dir)
    # First checkout base branch
    subprocess.run(['git', 'checkout', base_branch], check=True)
    # Attempt merge
    result = subprocess.run(['git', 'merge', target_branch],
                          capture_output=True, text=True)
    return result.returncode == 0  # True if merge successful

def detect_conflicts(repo_dir, prs):
    """Detect conflicts between PRs using git merge"""
    conflict_matrix = []
    pr_branches = [pr.head.ref for pr in prs]

    for i, pr1 in enumerate(prs):
        row = []
        for j, pr2 in enumerate(prs):
            if i == j:
                row.append(False)  # No self-conflict
                continue

            # Try merging pr2 into pr1
            try:
                # Clean any previous merge state
                os.chdir(repo_dir)
                subprocess.run(['git', 'merge', '--abort'],
                             capture_output=True, check=False)
                subprocess.run(['git', 'checkout', pr1.head.ref], check=True)

                merge_success = merge_branches(repo_dir, pr1.head.ref, pr2.head.ref)
                row.append(not merge_success)  # True if conflict (merge failed)
            except subprocess.CalledProcessError:
                row.append(True)  # Assume conflict if any error occurs

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
    os.chdir(repo_dir)
    result = subprocess.run(['git', 'symbolic-ref', 'refs/remotes/origin/HEAD'],
                          capture_output=True, text=True, check=True)
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