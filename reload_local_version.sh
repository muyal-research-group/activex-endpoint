#!/bin/bash
readonly x=/home/nacho/Programming/Python/activex/dist/axo-0.0.$1.tar.gz
poetry remove axo && poetry add $x
