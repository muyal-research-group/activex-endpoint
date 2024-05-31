from typing import Generator,Any
def byte_generator(data, chunk_size=1024)->Generator[bytes,Any,Any]:
    """
    Generator that yields chunks of data.
    
    Args:
    - data: The data to be chunked.
    - chunk_size: The size of each chunk in bytes.
    
    Yields:
    - Chunks of data of the specified chunk size.
    """
    for i in range(0, len(data), chunk_size):
        yield data[i:i + chunk_size]