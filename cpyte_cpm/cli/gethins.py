from . import style
from .http_session import get_session


def fetch_repo(url: str, back: str):
    """Fetch metadata from a single repo."""
    cleaned = url.strip("/")
    based = "/".join([cleaned, back])
    session = get_session()
    repo = session.get(based, timeout=10)
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
        style.print_warning(f"could not fetch group {group}: {e}")
        return []


def fetch_packages_list(repos: list[str]) -> list[dict]:
    """Fetch the complete list of packages from the registry.
    
    Returns a list of package dicts with 'name' and 'version' keys.
    """
    try:
        data = fetch_repo_multi(repos, "packages")
        return data if isinstance(data, list) else []
    except Exception as e:
        style.print_warning(f"could not fetch packages list: {e}")
        return []


def find_package_metadata(repos: list[str], package_name: str) -> dict:
    """Find metadata for a specific package by trying the metadata endpoint first.
    
    Tries to fetch actual metadata from the registry, falls back to packages list.
    """
    # First, get the version from the packages list
    packages = fetch_packages_list(repos)
    version = None
    for pkg in packages:
        if pkg.get("name") == package_name:
            version = pkg.get("version", "latest")
            break
    
    if not version:
        return None
    
    # Try to fetch actual metadata for the specific version
    if package_name.startswith("@"):
        path = f"metadata/group/{package_name[1:]}/{version}"
    else:
        path = f"metadata/{package_name}/{version}"
    
    try:
        return fetch_repo_multi(repos, path)
    except Exception:
        pass
    
    # Fallback: construct metadata from packages list
    if package_name.startswith("@"):
        download_url = f"{repos[0]}/packages/group/{package_name[1:]}/{version}.tar.gz"
    else:
        download_url = f"{repos[0]}/packages/{package_name}/{version}.tar.gz"
    
    return {
        "name": package_name,
        "version": version,
        "url": download_url,
        "checksum": "",
        "claims": {},
        "requires": [],
        "no_download": True,
    }
