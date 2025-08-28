
#!/bin/bash

export AXO_GOSSIP_SEEDS=tcp://0.0.0.0:7778
export AXO_ENDPOINT_ID=axo-endpoint-0

python3 ./axo_endpoint/main.py
