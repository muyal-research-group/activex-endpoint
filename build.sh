#!/bin/bash
readonly AXO_VERSION=${1:-20}
readonly ACTIVEX_ENV=${2:-dev}
readonly ACTIVEX_FULL_VERSION="0.0.${AXO_VERSION}"

echo "Removing Axo - ${ACTIVEX_FULL_VERSION}"
poetry remove axo
if [ "$ACTIVEX_ENV" == "dev" ]; then
    cp ~/Programming/Python/activex/dist/axo-${ACTIVEX_FULL_VERSION}.tar.gz axo.tar.gz
    docker build -f ./Dockerfile-dev -t nachocode/axo:endpoint-${ACTIVEX_FULL_VERSION} .
    poetry remove axo
    poetry add ./axo.tar.gz
else
    poetry add axo==${ACTIVEX_FULL_VERSION}
    docker build -f ./Dockerfile -t nachocode/activex:endpoint-${ACTIVEX_FULL_VERSION} .
fi

