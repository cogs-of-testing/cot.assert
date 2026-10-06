Cached rewrites are checked against the source's contents, as pytest main
does: a cache file holds a hash of the source instead of its mtime and size
(a PEP 552 checked-hash pyc). An edit that keeps the size within the same
second is no longer served from the cache, and a fresh checkout or a
restored cache no longer invalidates every file.
