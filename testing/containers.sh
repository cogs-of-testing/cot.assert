#!/bin/sh
# Run the test suite on Python 2.7 in a container.
#
#   testing/containers.sh {py27|pypy27} [pytest args...]
#
# The repository is mounted at /src and imported from source; hatchling cannot
# build on 2.7, so nothing is installed from it. pytest 4.6.11 (the last
# release for 2.7, and the one PyPy pins) lives in a per-image user base under
# .containers/. For pypy27, the rpython package of $PYPY_CHECKOUT (default
# ~/Projects/pypy/pypy) is mounted as a throwaway overlay under /pypy and put
# on sys.path. Only rpython: older checkouts carry a vendored pytest.py at
# their root that would shadow pytest 4.6.
set -eu

target=${1:?"usage: $0 py27|pypy27 [pytest args...]"}
shift

here=$(cd "$(dirname "$0")/.." && pwd)
pypy_checkout=${PYPY_CHECKOUT:-$HOME/Projects/pypy/pypy}

case $target in
py27)
    image=docker.io/library/python:2.7
    python=python
    extra_mount=
    extra_path=
    ;;
pypy27)
    image=docker.io/library/pypy:2.7
    python=pypy
    # overlay: rpython writes build caches into its tree, keep them off the host
    extra_mount="-v $pypy_checkout/rpython:/pypy/rpython:O"
    extra_path=:/pypy
    ;;
*)
    echo "unknown target: $target" >&2
    exit 2
    ;;
esac

userbase=/src/.containers/$target
mkdir -p "$here/.containers/$target"

# shellcheck disable=SC2086
exec podman run --rm -i \
    -v "$here:/src:z" $extra_mount \
    -w /src \
    -e PYTHONUSERBASE=$userbase \
    -e PYTHONPATH=/src/src:/src/testing$extra_path \
    -e PYTHONDONTWRITEBYTECODE=1 \
    -e PIP_DISABLE_PIP_VERSION_CHECK=1 \
    "$image" sh -c '
        py=$1; shift
        $py -c "import pytest" 2>/dev/null ||
            $py -m pip install -q --user "pytest==4.6.11"
        exec $py -m pytest -p no:cacheprovider "$@"
    ' sh "$python" "$@"
