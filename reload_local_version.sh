#!/bin/bash
readonly x=/home/nacho/Programming/Python/activex/dist/activex-0.0.$1.tar.gz
poetry remove activex && poetry add $x && cp $x ./activex.tar.gz

poetry remove activex
poetry add activex
