#!/bin/bash
readonly ACTIVEX_VERSION=${1:-20}
poetry remove activex
poetry add activex==0.0.${ACTIVEX_VERSION}
cp ~/Programming/Python/activex/dist/activex-0.0.${ACTIVEX_VERSION}.tar.gz
docker build -f ./Dockerfile -t nachocode/activex:endpoint .
poetry remove activex 
poetry add ./activex.tar.gz
