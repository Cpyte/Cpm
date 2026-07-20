import requests as rq


def fetch_repo(url: str, back: str):
    """Fetch metadata from a single repo."""
    cleaned = url.strip("/")
    based = "/".join([cleaned, back])
    repo = rq.get(based)
    repo.raise_for_status()
    return repo.json()


def fetch_repo_multi(repos: list[str], back: str):
    """Fetch metadata trying repos in priority order.

    Tries each repo in order. Returns the first successful result.
    Raises the last error if all repos fail.
    """
    last_error = None
    for url in repos:
        try:
            return fetch_repo(url, back)
        except Exception as e:
            last_error = e
            continue
    if last_error:
        raise last_error
    raise RuntimeError("no repositories configured")


def fetch_group(repos: list[str], group: str) -> list[str]:
    """Fetch package list for a group (e.g., @std -> ["@std/json", ...])."""
    # Strip the @ for the metadata path
    group_id = group.lstrip("@")
    
    # Use the standard format that works: metadata/@group_id/latest
    path = f"metadata/@{group_id}/latest"
    
    try:
        data = fetch_repo_multi(repos, path)
        return data.get("packages", [])
    except Exception as e:
        print(f"  Warning: could not fetch group {group}: {e}")
        return []


def fetch_packages_list(repos: list[str]) -> list[dict]:
    """Fetch the complete list of packages from the registry.
    
    Returns a list of package dicts with 'name' and 'version' keys.
    """
    try:
        data = fetch_repo_multi(repos, "packages")
        return data if isinstance(data, list) else []
    except Exception as e:
        print(f"  Warning: could not fetch packages list: {e}")
        return []


def find_package_metadata(repos: list[str], package_name: str) -> dict:
    """Find metadata for a specific package from the packages list.
    
    Since individual package metadata endpoints don't exist,
    we construct minimal metadata from the packages list.
    Note: The registry currently has package metadata but no downloadable files.
    """
    packages = fetch_packages_list(repos)
    for pkg in packages:
        if pkg.get("name") == package_name:
            # Use the package page URL format from the web interface
            pkg_url = f"{repos[0]}/package/{package_name}"
            # Construct minimal metadata that resolve_get expects
            return {
                "name": pkg["name"],
                "version": pkg.get("version", "latest"),
                "url": pkg_url,  # Use the package page URL
                "checksum": "",  # Not available in packages list
                "claims": {},    # Not available in packages list
                "requires": [],  # Not available in packages list
                "no_download": True,  # Flag to indicate no downloadable file
            }
    return None
