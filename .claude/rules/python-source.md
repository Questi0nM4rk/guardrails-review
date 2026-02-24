# Python Source Conventions

## Imports

- `from __future__ import annotations` — first line after module docstring, every file
- Modern type syntax: `X | None` not `Optional[X]`, `list[str]` not `List[str]`

## Error Handling

- Catch specific exceptions only — never `except Exception: pass`
- No bare `except:` — always name the exception type

## Type Safety

- `dict[str, Any]` is banned across module boundaries — use dataclasses
- All public functions have type annotations

## Testing

- Standalone test functions (no classes unless shared state needed)
- Mock at infrastructure boundaries (subprocess, urllib)
- `tmp_path` for filesystem tests
