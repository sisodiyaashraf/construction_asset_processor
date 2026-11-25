import os
import subprocess
import sys
from pathlib import Path

def run_cmd(cmd, check=True):
    print(f">> Running: {cmd}")
    res = subprocess.run(cmd, shell=True, text=True, capture_output=True)
    if res.stdout:
        print(res.stdout.strip())
    if res.stderr:
        print(res.stderr.strip(), file=sys.stderr)
    if check and res.returncode != 0:
        raise RuntimeError(f"Command failed with code {res.returncode}: {cmd}")
    return res

def main():
    root = Path(__file__).resolve().parent.parent
    os.chdir(root)
    print(f"Working directory: {root}")

    # 1. Backup current branch
    run_cmd("git branch -D main_backup", check=False)
    run_cmd("git branch main_backup")
    print("Backed up current main to 'main_backup'.")

    # 2. Checkout orphan branch to rebuild clean staged commits
    run_cmd("git checkout --orphan main_staged")
    run_cmd("git rm -rf .", check=False)

    # 3. Commit 1: Core Codebase, UI, Database, Config, Docs, Tests
    print("\n--- Creating Commit 1: Application Source & Database ---")
    run_cmd("git add .gitignore README.md requirements.txt main.py")
    run_cmd("git add app/ core/ ui/ reports/ scratch/")
    run_cmd("git add data/assets.db")
    run_cmd('git commit -m "feat: complete Construction Asset Processor workstation (Stages 1-13.2)"')

    # 4. Batch add excavator root images (25 files in 2 batches)
    print("\n--- Creating Excavator Root Batches ---")
    root_images = sorted([str(p.relative_to(root)).replace("\\", "/") for p in (root / "excavater").glob("*.png")])
    batch1 = root_images[:13]
    batch2 = root_images[13:]

    for p in batch1:
        run_cmd(f'git add "{p}"')
    run_cmd('git commit -m "feat(assets): add excavator primary assets batch 1"')

    for p in batch2:
        run_cmd(f'git add "{p}"')
    run_cmd('git commit -m "feat(assets): add excavator primary assets batch 2"')

    # 5. Batch add 'other images' (136 files in 12 batches of ~11-12 files)
    print("\n--- Creating Other Images Batches ---")
    other_images = sorted([str(p.relative_to(root)).replace("\\", "/") for p in (root / "excavater" / "other images").glob("*.png")])
    batch_size = 12
    num_batches = (len(other_images) + batch_size - 1) // batch_size

    for i in range(num_batches):
        batch = other_images[i * batch_size : (i + 1) * batch_size]
        for p in batch:
            run_cmd(f'git add "{p}"')
        run_cmd(f'git commit -m "feat(assets): add catalog assets batch {i + 1} of {num_batches}"')

    # 6. Replace main branch with main_staged
    print("\n--- Updating main branch ---")
    run_cmd("git checkout -B main")
    run_cmd("git branch -D main_staged", check=False)

    print("\nSuccessfully prepared clean, chunked commit series on 'main'!")
    run_cmd("git log --oneline")

if __name__ == "__main__":
    main()
