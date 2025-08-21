# Running Tests

This project includes a comprehensive unit test suite that verifies all core functionality.

## Test Structure

The test suite is organized like the frond project with focused unit tests:

```
tests/
├── lib.rs                      # Test module declarations
├── pathfinding/
│   ├── mod.rs
│   └── bfs.rs                  # BFS algorithm tests
├── parsing/
│   ├── mod.rs
│   ├── lookup.rs               # Artist lookup tests
│   └── metadata.rs             # Metadata parsing tests  
└── utils/
    ├── mod.rs
    └── format.rs               # Number formatting tests
```

## Test Coverage

- **Pathfinding**: BFS algorithm, path finding, connection filtering
- **Parsing**: JSON/NDJSON parsing, error handling, data validation
- **Utils**: Number formatting with thousands separators
- **Edge cases**: Empty data, malformed input, missing connections

## Running Tests

Simply run:

```bash
cargo test
```

All 15 tests should pass quickly. Tests use temporary files and are fully independent - no shared state or race conditions.