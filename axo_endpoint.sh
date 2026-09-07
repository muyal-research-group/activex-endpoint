#!/usr/bin/env bash
# Caps glibc malloc arenas so the service's baseline virtual memory footprint
# stays small — otherwise forked worker processes inherit a bloated address
# space and can blow through their RLIMIT_AS before doing any real work.
export MALLOC_ARENA_MAX=2
exec python3 -m axo_endpoint "$@"
