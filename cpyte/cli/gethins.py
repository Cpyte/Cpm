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
    
    # Try different metadata path formats for compatibility
    paths_to_try = [
        f"metadata/@{group_id}/latest",    # Standard format
        f"metadata/{group_id}/latest",     # Alternative without @
        f"group/{group_id}/latest",        # Group-based format
    ]
    
    last_error = None
    for path in paths_to_try:
        try:
            data = fetch_repo_multi(repos, path)
            packages = data.get("packages", [])
            if packages:
                return packages
        except Exception as e:
            last_error = e
            continue
    
    # If all paths fail, return empty list (group may not exist)
    if last_error:
        print(f"  Warning: could not fetch group {group}: {last_error}")
    return []
