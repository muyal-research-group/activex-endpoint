
from axo_shared.client import AxoEndpointClient

ADDRESS = "tcp://localhost:5555"



def main():
    with AxoEndpointClient(ADDRESS) as client:
        for job_id in ["7295fb148971451a8fbe49fcf5a8fc7e", "92cac8e15c3540a7bcd312574cff8344"]:
            result = client.get_job_result(job_id=job_id)
            print("Result for job_id", job_id, "->", result)


if __name__ == "__main__":
    main()