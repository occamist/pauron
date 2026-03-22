import hashlib
import subprocess
import os
import logging
import shutil
import re
import argparse

import requests


logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def setup_ssh_for_aur():
    git_email = os.environ.get("GIT_EMAIL", "pauron@bot.com")
    git_name = os.environ.get("GIT_NAME", "Pauron Bot")
    subprocess.run(["git", "config", "--global", "user.email", git_email], check=True)
    subprocess.run(["git", "config", "--global", "user.name", git_name], check=True)

    ssh_dir = os.path.expanduser("~/.ssh")
    os.makedirs(ssh_dir, exist_ok=True, mode=0o700)

    key_path = os.path.join(ssh_dir, "aur_key")
    aur_key = os.environ["AUR_SSH_KEY"]

    # Write key exactly as received, ensuring it ends with newline
    with open(key_path, "w") as f:
        f.write(aur_key)
        if not aur_key.endswith("\n"):
            f.write("\n")

    os.chmod(key_path, 0o600)

    # Test the key format first
    try:
        result = subprocess.run(
            ["ssh-keygen", "-l", "-f", key_path],
            capture_output=True,
            text=True,
            check=True,
        )
        logger.info(f"SSH key fingerprint: {result.stdout.strip()}")
    except subprocess.CalledProcessError as e:
        logger.error(f"SSH key validation failed: {e.stderr}")
        return

    # Add the real AUR host key to known_hosts
    try:
        subprocess.run(
            ["ssh-keyscan", "-H", "aur.archlinux.org"],
            stdout=open(os.path.join(ssh_dir, "known_hosts"), "w"),
            check=True,
        )
        logger.info("Added AUR host key to known_hosts")
    except Exception as e:
        logger.warning(f"Failed to add host key: {e}")

    # Preserve existing SSH config and add AUR entry
    ssh_config_path = os.path.join(ssh_dir, "config")
    existing_config = ""
    if os.path.exists(ssh_config_path):
        with open(ssh_config_path, "r") as f:
            existing_config = f.read()
    
    # Only add AUR config if not already present
    if "Host aur.archlinux.org" not in existing_config:
        aur_config = f"""
# Added by Pauron
Host aur.archlinux.org
    IdentityFile {key_path}

"""
        with open(ssh_config_path, "a") as f:
            f.write(aur_config)

    # Test SSH connection exactly
    try:
        result = subprocess.run(
            [
                "ssh",
                "-i",
                key_path,
                "-T",
                "aur@aur.archlinux.org",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        logger.info(f"SSH test completed with exit code: {result.returncode}")
        if result.stderr:
            logger.info(f"SSH stderr: {result.stderr}")
        if result.stdout:
            logger.info(f"SSH stdout: {result.stdout}")
    except Exception as e:
        logger.warning(f"SSH connection test failed: {e}")


def clone_and_parse(pkg_name: str, aur_repo: str) -> dict[str, None | str] | None:
    """Clone AUR package and parse PKGBUILD metadata"""
    try:
        if os.path.exists(pkg_name):
            pkgbuild_path = os.path.join(pkg_name, "PKGBUILD")
            return parse_pkgbuild(pkgbuild_path)

        logger.info(f"Cloning {aur_repo}")
        subprocess.run(
            ["git", "clone", aur_repo],
            capture_output=True,
            text=True,
            check=True,
        )
        pkgbuild_path = os.path.join(pkg_name, "PKGBUILD")
        if not os.path.exists(pkgbuild_path):
            raise FileNotFoundError("PKGBUILD not found")

        logger.info("Parsing PKGBUILD...")
        return parse_pkgbuild(pkgbuild_path)
    except subprocess.CalledProcessError as e:
        logger.error(f"Git clone failed: {e}")
        logger.error(f"  Command: {e.cmd}")
        logger.error(f"  Return code: {e.returncode}")
        logger.error(f"  stdout: {e.stdout}")
        logger.error(f"  stderr: {e.stderr}")
        return None
    except Exception as e:
        logger.error(f"Error: {e}")
        return None


def parse_pkgbuild(path) -> dict[str, str | None]:
    """Extract specific metadata from PKGBUILD"""
    metadata: dict[str, str | None] = {
        "pkgver": None,
        "sha256sums": None,
        "_commit": None,
        "source": None,
        "owner_name": None,
        "repo_name": None,
    }

    with open(path, "r") as f:
        lines = f.readlines()

    for line in lines:
        line = line.strip()

        if not line or line.startswith("#"):
            continue

        for field in metadata.keys():
            if line.startswith(f"{field}="):
                # Split by = and get the value part
                value = line.split("=", 1)[1].strip()
                # Remove trailing comments
                value = value.split("#")[0].strip()
                metadata[field] = value

                if field == "source":
                    parts = value.split("::")[-1].split("/")
                    metadata["owner_name"], metadata["repo_name"] = parts[3], parts[4]
                break

    return metadata


def display_metadata(metadata):
    """Display extracted metadata"""
    if not metadata:
        logger.error("No metadata to display")
        return

    logger.info("Extracted metadata:")
    for key, value in metadata.items():
        logger.info(f"  {key}: {value}")


def get_latest_github_release_tag(owner: str, repo: str):
    """Get latest GitHub release tag"""
    try:
        url = f"https://api.github.com/repos/{owner}/{repo}/releases/latest"
        response = requests.get(url=url)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        logger.error(f"Failed to get latest Github release tag: {e}")
        return None

    return data["tag_name"]


def calculate_sha256(owner: str, repo: str, tag: str) -> str | None:
    """Get sha256 hash for a given tag using GitHub API"""
    url = f"https://github.com/{owner}/{repo}/archive/{tag}.tar.gz"
    sha256_hash = hashlib.sha256()

    try:
        response = requests.get(url, stream=True)
        response.raise_for_status()
        for chunk in response.iter_content(chunk_size=8192):
            sha256_hash.update(chunk)

        digest = sha256_hash.hexdigest()
        logger.info(f"SHA256 hash for release tag({tag}): {digest}")
        return digest
    except Exception as e:
        logger.error(f"Failed to calculate SHA256 hash for release tag({tag}): {e}")
        return None


def calculate_commit(owner: str, repo: str, tag: str) -> str | None:
    """Get commit hash for a given tag using GitHub API"""
    url = f"https://api.github.com/repos/{owner}/{repo}/git/refs/tags/{tag}"

    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        commit_hash = data["object"]["sha"]

        logger.info(f"Commit hash for release tag({tag}): {commit_hash}")
        return commit_hash
    except Exception as e:
        logger.error(f"Failed to get commit hash for release tag({tag}): {e}")
        return None


def update_pkgbuild_file(file: str, new_pkgver: str, new_sha256: str, new_commit: str):
    with open(file, "r") as f:
        content = f.read()

    # patch the values
    content = re.sub(r"pkgver=.*", f"pkgver={new_pkgver}", content)
    content = re.sub(r"sha256sums=\('.*?'\)", f"sha256sums=('{new_sha256}')", content)
    content = re.sub(r"_commit=\('.*?'\)", f"_commit=('{new_commit}')", content)

    with open(file, "w") as f:
        f.write(content)
    logger.info("PKGBUILD file was updated successfully")


def update_dot_srcinfo_file(
    file: str, new_pkgver: str, new_sha256: str, owner: str, repo: str, latest_tag: str
):
    with open(file, "r") as f:
        content = f.read()

    # patch the values
    content = re.sub(r"pkgver = .*", f"pkgver = {new_pkgver}", content)
    content = re.sub(r"sha256sums = .*", f"sha256sums = {new_sha256}", content)
    content = re.sub(
        r"source = .*?\.tar\.gz::https://github\.com/.*?/.*?/archive/.*?\.tar\.gz",
        f"source = {repo}-{latest_tag}.tar.gz::https://github.com/{owner}/{repo}/archive/{latest_tag}.tar.gz",
        content,
    )

    with open(file, "w") as f:
        f.write(content)
    logger.info(".SRCINFO file was updated successfully")


def push_changes(latest_tag: str):
    subprocess.run(["git", "add", "."], check=True)
    commit_msg = latest_tag
    if commit_msg[0] != "v":
        commit_msg = "v" + latest_tag
    subprocess.run(["git", "commit", "-m", f"{commit_msg}"], check=True)
    subprocess.run(["git", "push"], check=True)
    logging.info(f"Successfully committed and pushed {latest_tag}")


def get_git_config(key) -> str | None:
    try:
        result = subprocess.run(["git", "config", "--global", key], capture_output=True, text=True, check=True)
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        return None


def restore_git_config(key, value):
    if value is not None:
        subprocess.run(["git", "config", "--global", key, value], check=True)
    else:
        subprocess.run(["git", "config", "--global", "--unset", key], check=False)


def main():
    parser = argparse.ArgumentParser(
        description="Update AUR package from GitHub releases"
    )
    parser.add_argument(
        "--pkg-name", "-p", required=True, help="AUR package name (e.g., k3sup)"
    )
    args = parser.parse_args()

    pkg_name = args.pkg_name
    aur_repo = f"ssh://aur@aur.archlinux.org/{pkg_name}.git"
    original_email = get_git_config("user.email")
    original_name = get_git_config("user.name")
    print(original_email)
    print(original_name)

    try:
        pass
        setup_ssh_for_aur()

        logger.info(f"Processing AUR package: {aur_repo}")
        metadata = clone_and_parse(pkg_name, aur_repo)
        display_metadata(metadata)

        logger.info("Checking for latest Github release version...")
        owner, repo = metadata["owner_name"], metadata["repo_name"]
        latest_tag: str = get_latest_github_release_tag(owner, repo)
        current_version, new_version = metadata.get("pkgver"), latest_tag.lstrip("v")
        if new_version == current_version:
            logger.info(
                f"Newest Github version({new_version}) and current PKGBUILD version({current_version}) are same, quitting."
            )
            return

        new_sha_hash, new_commit_hash = (
            calculate_sha256(owner, repo, latest_tag),
            calculate_commit(owner, repo, latest_tag),
        )

        ## duplicate
        for filename in ["PKGBUILD", ".SRCINFO"]:
            filename = os.path.join(pkg_name, filename)
            if os.path.exists(filename):
                old_filename = f"{filename}_old"
                os.rename(filename, old_filename)
                shutil.copy2(old_filename, filename)
            else:
                logging.warning(f"File {filename} not found")

        ## path values in files
        file = os.path.join(pkg_name, "PKGBUILD")
        update_pkgbuild_file(file, new_version, new_sha_hash, new_commit_hash)
        file = os.path.join(pkg_name, ".SRCINFO")
        update_dot_srcinfo_file(file, new_version, new_sha_hash, owner, repo, latest_tag)

        ## remove
        for filename in ["PKGBUILD_old", ".SRCINFO_old"]:
            filename = os.path.join(pkg_name, filename)
            if os.path.exists(filename):
                os.remove(filename)

        os.chdir(pkg_name)
        push_changes(latest_tag)
    finally:
        restore_git_config("user.email", original_email)
        restore_git_config("user.name", original_name)


if __name__ == "__main__":
    main()
