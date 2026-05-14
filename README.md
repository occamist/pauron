# Pauron
[![PyPI](https://img.shields.io/pypi/v/pauron)](https://pypi.org/project/pauron)
[![CI Build](https://github.com/occamist/pauron/actions/workflows/publish.yaml/badge.svg)](https://github.com/occamist/pauron/actions/workflows/publish.yaml)
[![AUR Sync Status](https://img.shields.io/github/actions/workflow/status/occamist/pauron/update-aur-packages.yaml?label=Syncing%20My%20AUR)](https://github.com/occamist/pauron/actions/workflows/update-aur-packages.yaml)
[![License](https://img.shields.io/github/license/occamist/pauron)](https://github.com/occamist/pauron/blob/main/LICENSE)



Pauron is an automation bot for AUR repositories. You can think it of like watcher for github releases. The name emerges from Sauron but with "P" beginning. 

It patches PKGBUILD & .SRCINFO files when a new release is detected at upstream then pushes to AUR repository. This way, you can maintain more AUR repositories with less effort on updating new release versions.

> [!NOTE]  
> We only support GitHub upstream URLs for AUR packages.

### How to use 

You can fork this repo and tweak update-aur-packages.yaml after you have added `AUR_SSH_KEY` to GitHub secrets and adjust accordingly for your package name.

or

```sh
AUR_SSH_KEY="$(cat ~/.ssh/pauron)" pipx run pauron -p my-package-name
```

or

```sh
pipx install pauron
pipx ensurepath
AUR_SSH_KEY="$(cat ~/.ssh/pauron)" pauron -p my-package-name 
```
