#!/bin/bash
readonly AXO_FULL_VERSION=${1:-20}
readonly AXO_ENV=${2:-dev}
readonly AXO_LIB_FULL_VERSION=${3:-$AXO_FULL_VERSION}
echo "Removing Axo - ${AXO_FULL_VERSION}"
poetry remove axo
if [ "$AXO_ENV" == "dev" ]; then
    cp ~/Programming/Python/axo/dist/axo-${AXO_LIB_FULL_VERSION}.tar.gz axo.tar.gz
    docker build -f ./Dockerfile-dev -t nachocode/axo:endpoint-${AXO_FULL_VERSION} .
    poetry remove axo
    poetry add ./axo.tar.gz
else
    poetry add axo==${AXO_LIB_FULL_VERSION}
    docker build -f ./Dockerfile -t nachocode/axo:endpoint-${AXO_FULL_VERSION} .
fi

