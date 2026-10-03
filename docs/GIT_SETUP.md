# Git and GitHub Setup

This source package intentionally contains no `.git` directory. Initialise the
repository locally after extracting it.

The Git commands below work in PowerShell, Git Bash, macOS Terminal and Linux.
You do not need to run a local build before the first push; the included
GitHub Actions workflow will run the automated suites.

## 1. Create an empty GitHub repository

Create an empty repository named `home-energy-scada`. Do not ask GitHub to add
a README, `.gitignore` or licence because this package already contains the
repository files.

## 2. Verify the extracted source

Confirm that the directory contains `README.md`, `.gitignore`, `source/`,
`tests/`, `docs/` and `.github/`. It must not contain `node_modules`,
`dist`, deployment ZIPs, rollback ZIPs or real `.env` files.

## 3. Initialise and commit

Run these commands from the extracted project root:

```bash
git init -b main
git status
git add .
git status
git commit -m "chore: import verified v0.6.2 source baseline"
git tag -a v0.6.2-rc.1 -m "Home Energy SCADA v0.6.2 release candidate"
```

Review the second `git status` before committing. Generated or sensitive files
should not be listed.

If Git asks for your identity:

```bash
git config --global user.name "Your Name"
git config --global user.email "your-github-email@example.com"
```

## 4. Connect and push

SSH is recommended when an SSH key is already configured:

```bash
git remote add origin git@github.com:YOUR_GITHUB_USERNAME/home-energy-scada.git
git push -u origin main
git push origin v0.6.2-rc.1
```

HTTPS is also valid when authenticated with a supported GitHub credential:

```bash
git remote add origin https://github.com/YOUR_GITHUB_USERNAME/home-energy-scada.git
git push -u origin main
git push origin v0.6.2-rc.1
```

Do not use `git push --force` for the initial upload.

### Windows / WSL notes

PowerShell, Git Bash and WSL can all initialise and push the repository with the
same Git commands. When developing primarily with Linux tooling, keeping the
working tree inside the WSL filesystem is recommended.

If you also want to run the Python suites from Windows PowerShell:

```powershell
Push-Location source/frontend-react
npm ci
npm test
npm run build
Pop-Location

py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
$env:PYTHONPATH = "source;source/lightsail-collector"
python -m unittest discover -s tests -p "test_*.py" -q
$env:PYTHONPATH = "source/lightsail-collector"
python -m unittest discover -s source/lightsail-collector/tests -p "test_*.py" -q
```

Run `source/scripts/build-current-artifacts.sh` from Git Bash or WSL because
the deterministic builder uses standard Unix `zip`, `unzip` and shell tools.

## 5. Promote the release

The automated suites have passed, but target-browser and real-device smoke is
still pending. After those checks and the production deployment succeed, add
the immutable final tag to the same verified commit:

```bash
git switch main
git pull --ff-only
git tag -a v0.6.2 -m "Home Energy SCADA v0.6.2"
git push origin v0.6.2
```

Attach generated deployment and rollback ZIPs to the GitHub Release. Do not
commit those binaries to the repository.

## Normal development flow

Keep `main` as the accepted baseline. Create a short-lived branch for each
change:

```bash
git switch main
git pull --ff-only
git switch -c feature/short-description
```

Use `feature/`, `fix/`, `docs/`, `chore/` or `hotfix/` as appropriate.
Push the branch and open a Pull Request into `main`. Let CI complete, review the
diff, then merge through the PR rather than pushing directly to `main`.

A permanent `develop` branch is unnecessary for the current single-maintainer
project.
