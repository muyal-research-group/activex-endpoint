## [0.0.1a9] - 2025-08-15 🎉

### Added
- Introduced `from_multipart_to_task_and_envelope` function to parse new Axo protocol requests. 
  - Handles multipart frames:
    - `0`: `b"axo"`
    - `1`: `b"v1"`
    - `2`: operation (bytes)
    - `3`: `b"application/json"`
    - `4`: envelope JSON
    - `5+`: payload frames (per operation)
  - Returns: `Ok((task, envelope_model, payload_frames))` or `Err(AxoError)`.


## [0.0.1a8] - 2025-08-10
## [0.0.1a7] - 2025-08-10
## [0.0.1a6] - 2025-08-08
## [0.0.1a5] - 2025-08-08
## [0.0.1a4] - 2025-08-07

