# User-extensible knowledge tools

Drop custom tool modules in `./tools/` and reference them in `hypeagent.yaml`:

```yaml
knowledge:
  tools:
    - name: my_tool
      module: tools.my_app.my_tool
      description: What the tool returns.
```

Each module must expose `run(ctx, arguments) -> str`.
