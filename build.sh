#!/bin/bash
readonly ACTIVEX_VERSION=${1:-20}
readonly ACTIVEX_ENV=${2:-dev}
readonly ACTIVEX_FULL_VERSION="0.0.${ACTIVEX_VERSION}"
readonly ACTIVEX_PRE_RELEASE=${3:-alpha}

poetry remove activex
poetry add activex==${ACTIVEX_FULL_VERSION}
if [ "$ACTIVEX_ENV" == "dev" ]; then
    cp ~/Programming/Python/activex/dist/activex-${ACTIVEX_FULL_VERSION}.tar.gz
    docker build -f ./Dockerfile-dev -t nachocode/activex:endpoint-${ACTIVEX_FULL_VERSION}-${ACTIVEX_PRE_RELEASE} .
    poetry remove activex 
    poetry add ./activex.tar.gz
else
    docker build -f ./Dockerfile -t nachocode/activex:endpoint-${ACTIVEX_FULL_VERSION}-${ACTIVEX_PRE_RELEASE} .
fi

