# Reference only — tests axo_endpoint/old/ code, not maintained against new code.
from axo_endpoint.endpoints import EndpointManager
from mictlanx.services import Summoner
from option import Some,NONE


def test_em():
    summoner = Summoner(
        ip_addr     = "localhost",
        api_version = Some(3),
        network     = NONE,
        protocol    = "http",
        port        = 15000
    )
    em = EndpointManager(axo_endpoint_id="axo-endpoint-0",summoner=summoner)
    res = em.deploy_endpoint_bulk(rf=5,network_id="mictlanx")
    print("RES",res)
    assert res.is_ok
    res = em.srink(rf=5)
    print("RES",res)
    assert res.is_ok
