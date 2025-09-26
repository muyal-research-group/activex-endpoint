#!/bin/bash
readonly x=/home/nacho/Programming/Python/axo/dist/axo-0.0.$1.tar.gz
poetry remove axo || true
poetry add $x
