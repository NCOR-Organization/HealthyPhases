"""Object-storage folder matching with path-component boundaries."""


def source_folder(prefix: str | None, key: str | None) -> str | None:
    prefix = (prefix or "").strip("/")
    directory = (key or "").strip("/").rpartition("/")[0]
    return "/".join(part for part in (prefix, directory) if part) or None


def matches_path(folder: str | None, paths: list[str]) -> bool:
    if not folder:
        return False
    return any(
        folder == path or folder.startswith(path + "/")
        for value in paths
        if (path := value.strip("/"))
    )


def parent_paths(folders: list[str]) -> list[str]:
    return sorted(
        {
            "/".join(folder.split("/")[:length])
            for folder in folders
            for length in range(1, len(folder.split("/")) + 1)
        }
    )
