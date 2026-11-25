import os
import subprocess
import sys
from pathlib import Path

def run_cmd(cmd, check=True):
    res = subprocess.run(cmd, shell=True, text=True, capture_output=True)
    if res.returncode != 0 and check:
        print(f"Error stdout: {res.stdout}")
        print(f"Error stderr: {res.stderr}")
        raise RuntimeError(f"Command failed with code {res.returncode}: {cmd}")
    return res

def main():
    root = Path(__file__).resolve().parent.parent
    os.chdir(root)
    print(f"Project Root: {root}")

    # Set user info for commits
    os.environ["GIT_AUTHOR_NAME"] = "sisodiyaashraf"
    os.environ["GIT_AUTHOR_EMAIL"] = "ashrafsisodiya478@gmail.com"
    os.environ["GIT_COMMITTER_NAME"] = "sisodiyaashraf"
    os.environ["GIT_COMMITTER_EMAIL"] = "ashrafsisodiya478@gmail.com"

    # Use a custom temporary index so we don't mess with the working directory
    temp_index = root / ".git" / "temp_chunk_index"
    if temp_index.exists():
        temp_index.unlink()
    os.environ["GIT_INDEX_FILE"] = str(temp_index)

    commits = []

    # 1. Base Commit: Source code, database, tests, config, readme, gitignore
    print("\n--- [1/15] Staging Application Codebase & Database ---")
    run_cmd("git add .gitignore README.md requirements.txt main.py")
    run_cmd("git add app/ core/ ui/ reports/ scratch/")
    run_cmd("git add data/assets.db")
    tree1 = run_cmd("git write-tree").stdout.strip()
    msg1 = "feat: complete Construction Asset Processor workstation (Stages 1-13.2)"
    commit1 = run_cmd(f'git commit-tree {tree1} -m "{msg1}"').stdout.strip()
    commits.append((commit1, "Application Codebase & Database (~7 MB)"))
    print(f"  Commit 1: {commit1[:8]} ({commits[-1][1]})")

    parent = commit1

    # 2. Excavator Root Assets (25 images split into 2 batches)
    root_images = sorted([p.relative_to(root).as_posix() for p in (root / "excavater").glob("*.png")])
    batches = [
        ("Excavator Primary Assets (Part 1/2)", root_images[:13]),
        ("Excavator Primary Assets (Part 2/2)", root_images[13:])
    ]

    for title, file_list in batches:
        for f in file_list:
            run_cmd(f'git add "{f}"')
        tree = run_cmd("git write-tree").stdout.strip()
        msg = f"feat(assets): add {title.lower()}"
        commit = run_cmd(f'git commit-tree {tree} -p {parent} -m "{msg}"').stdout.strip()
        commits.append((commit, title))
        parent = commit
        print(f"  Commit {len(commits)}: {commit[:8]} ({title})")

    # 3. Catalog Other Images (136 images split into 12 batches of 11-12 images)
    other_images = sorted([p.relative_to(root).as_posix() for p in (root / "excavater" / "other images").glob("*.png")])
    batch_size = 12
    num_batches = (len(other_images) + batch_size - 1) // batch_size

    for i in range(num_batches):
        title = f"Catalog Assets Batch {i + 1}/{num_batches}"
        batch_files = other_images[i * batch_size : (i + 1) * batch_size]
        for f in batch_files:
            run_cmd(f'git add "{f}"')
        tree = run_cmd("git write-tree").stdout.strip()
        msg = f"feat(assets): add catalog images batch {i + 1} of {num_batches}"
        commit = run_cmd(f'git commit-tree {tree} -p {parent} -m "{msg}"').stdout.strip()
        commits.append((commit, title))
        parent = commit
        print(f"  Commit {len(commits)}: {commit[:8]} ({title})")

    # Clean up temp index
    if temp_index.exists():
        temp_index.unlink()
    if "GIT_INDEX_FILE" in os.environ:
        del os.environ["GIT_INDEX_FILE"]

    # Point main to the final commit
    final_commit = commits[-1][0]
    print(f"\nFinal commit hash: {final_commit}")
    run_cmd(f"git update-ref refs/heads/main {final_commit}")
    run_cmd("git reset") # Sync index to main without touching working directory

    print("\nVerifying git log on main:")
    res = run_cmd("git log --oneline -n 16")
    print(res.stdout)

    # Save commit plan to JSON for sequential pushing
    import json
    plan_file = root / "scratch" / "push_plan.json"
    with open(plan_file, "w") as f:
        json.dump(commits, f, indent=2)
    print(f"Push plan saved to {plan_file} ({len(commits)} commits ready).")

if __name__ == "__main__":
    main()
