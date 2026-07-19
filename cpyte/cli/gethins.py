import requests as rq

def fetch_repo(url : str, back : str):
    cleaned = url.strip("/")
    based = "/".join([cleaned, back])
    repo = rq.get(based)
    repo.raise_for_status()
    return repo.json()