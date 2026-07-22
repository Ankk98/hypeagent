# User-extensible platform connectors

Drop custom connectors in `./platforms/` and reference them in `hypeagent.yaml`:

```yaml
platform:
  connector: ./platforms/my_app.py
```

See the implementation plan for the `PlatformConnector` contract.
